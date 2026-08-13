# MathPrint renderer + reverse-engineering

A standalone experimental model of TI-84 Plus OS 2.55MP MathPrint layouts. It
uses ROM-extracted font bitmaps, executable translations of closed ROM routines,
and trace-fitted box geometry for the remaining compositor. It is not an
emulator. Deployed beside the wiki at `/mathprint/` (outside the mdBook). The
reader-facing write-up is
[`docs/sub-equation-display.md`](../../docs/sub-equation-display.md).

## Interactive page

| File | Role |
|------|------|
| `index.html`, `style.css` | the interactive page |
| `app.js` | renderer and three labeled timelines: RE-generated writes, captured writes, and model elements |
| `rom-engine.js` | direct JavaScript translations of closed page `0x39`, page `0x34`, and page `0x01` routines |
| `font.json` | large (`07:45FF`) + small (`03:4CD6`) font glyphs, extracted from ROM |
| `token-strings.json` | single- and two-byte token display strings selected by `01:6702` |
| `layout.json` | page `0x39` class-table records and selected descriptors consumed by the translated routines |
| `record-programs.json` | six retained settled-record fixtures used only by offline comparisons |
| `draw-order.json` | accepted visible-pixel LCD mutations from the retained integral traces |
| `tools/mathprint-construction-oracles.json` | fresh settled graphs and accepted-write hashes for independently constructed expressions |
| `tools/mathprint-exponential-logbase-oracles.json` | fresh graph and accepted-write hashes for $e^x$, $10^x$, and `logBASE(` construction |
| `tools/mathprint-matrix-oracles.json` | fresh matrix graphs, result origins, synchronous accepted-write hashes, and interrupt classification |
| `tools/mathprint-grouping-oracles.json` | fresh grouping and nested absolute-value graphs plus accepted-write hashes |
| `tools/mathprint-structural-base-oracles.json` | fresh structural power-base and nested absolute/radical graphs plus accepted-write hashes |
| `tools/mathprint-named-token-oracles.json` | fresh counted-token spelling graphs plus accepted-write hashes in flat, raised, and structural contexts |
| `tools/mathprint-two-byte-token-oracles.json` | fresh list, matrix-name, equation-variable, and string-variable graphs plus accepted-write and framebuffer hashes |

`rom-engine.js` translates handler lookup, row-cell emission, direct-glyph and
delimiter classification, `_KeyToString` index arithmetic, descriptor selection
and iteration, fraction endpoints, class-6 row stepping, and the settled-redraw
point and axis-aligned line wrappers at `34:5D96`–`34:5EA6`. It returns an
explicit unresolved result where the `ram:025E`/`ram:0254` family-shape
predicates remain open.

The settled-redraw object dispatcher at `34:700C` is also translated as a
13-entry kind-to-handler table. Record-field decoding remains explicit work;
the trace shows transient records in high RAM that are absent from the final dump.

The page-`34` parse-ahead family at `34:5A99`–`34:5CAC` is translated with its
six public and internal entry modes, token-class tables, delimiter counters,
returned registers, flags, and `0x9D02`–`0x9D05` scratch bytes. Multi-argument
and generic-function construction uses the internal `34:5AA3` entry to check
each nested argument boundary. A retained summation trace pins all four
`34:5AA3` calls against the native buffer; the remaining mode branches are
byte-decoded and regression-tested but do not all have independent dynamic
oracles.

The function-opener predicate at `34:5A05` is also translated. It dispatches
ordinary tokens through `34:5A52`, `BB` tokens through `34:5A28`, and `EF`
tokens through `34:5A14`. Raw native input can therefore retain structural
children inside the full ROM-classified function-token ranges instead of a
preview-name allowlist. The renderer still rejects structural record type
`0x2C`, whose constructor and render dispatch remain unresolved.

Render-record type `0x22` is translated through `34:622F`. The interactive
integral sign now uses its exact vertical-segment and four-point operation order
instead of stretching glyph `0x08`.

Render-record type `0x20` is translated through its child traversal and rule
emission at `34:620A`. Fractions now draw numerator, denominator, then the
inclusive horizontal rule computed from both child `+7` widths and the parent
`+0x0B` coordinate. Child placement within each record remains open.

Render-record type `0x2A` is translated as a child-1 traversal through
`34:6375` and `34:636C`. The record emits no drawing primitive of its own.

Render-record type `0x27` is translated through the root-hook bitmap, vertical
stem, child selection, inclusive vinculum, and child traversal at `34:62A1`.
The compositor carries the selected child's record-width metric separately from
ink width and pen advance; this reproduces the cursor-free radical history echo
without applying the wider editable-entry metric.

Render-record type `0x21` executes the absolute-value bar pair followed by its
child. Type `0x24` executes nth-root index, hook, stem, radicand, and vinculum
operations in ROM order.

The complete structural render table at `34:6119`, types `0x1F`–`0x2B`, is
represented by an executable record-graph walker. The walker resolves child
IDs, applies each child's `+0x0B`/`+0x0D` local origin, preserves depth changes,
and emits ordered glyph, bitmap, point, line, compound-shape, and leaf
operations. A full settled expression enters through a type-`0x00` leaf program
at `34:660A`. `executeSettledRecordProgram()` consumes that payload in order,
invokes embedded structural records, advances the shared pen by each record's
`+9` metric, and maps single- and two-byte tokens through the ROM-extracted
counted strings selected by `smallfont_glyph_ptr` at `01:6702`. The two-byte
selector preserves the `5Eh` banks and the `BBh` clamp. Live settled
traces identify types `0x23`, `0x25`, `0x26`, `0x28`, `0x29`, and `0x2B` as
`nDeriv(`, $e^x$, $10^x$, `logBASE(`, summation, and a dimensioned matrix.

`tools/analyze_mathprint_records.py` replays a full-range TLMT memory snapshot
and writes, then captures 20-byte root/current records only when `34:6105` uses
the render table at `34:6119`. The decoder preserves offset-based field names
until a handler establishes a type-specific meaning. `--graph-json` exports
the final settled record program, its reachable nodes, and a semantic
`expression` tree decoded from their child IDs and payload bytes. Postfix
type-`0x2A` records bind to the expression immediately before their embedded
marker. `EF 1E` remains an explicit extended token because the renderer maps it
to display code `0xF7`, the empty template square. This tree identifies what the
trace contains without inspecting its screenshot. It describes the settled
render graph, not the editor/parser representation before `34:4900`.
The analyzer selects the first post-key `34:660A` entry at the shallowest Z80
stack depth. The exporter pairs
parent/index observations at `34:6CCD` with the resolved child ID and record
pointer at `34:6CD8`, so the export includes structural records, leaf records,
and leaf payload bytes beginning at `+0x13`. The ordered `dispatches` array
retains secondary structural passes constructed while rendering a leaf, such
as an exponent or nested fraction. An `EF type id_lo id_hi` payload sequence
references one of those structural records. Each dispatch also records the
live `ram:8DFE`/`ram:8E00` viewport origin used by the primitive wrappers.

`app.js` is organized in sections: box primitives → layout constructs → text runs
→ expression parser → canvas rendering → UI. A "box" is `{rows, baseline, marks,
adv}`; `adv` (pen advance) is separate from bitmap width so glyphs can overhang.
The marks are model-local composition metadata, not captured OS pen state. The
arbitrary-expression compositor is still reconstructed rather than translated.

## Tooling

| Tool | Purpose |
|------|---------|
| `export-font.py` | ROM → `font.json` (glyph data for the renderer and its font-table tab) |
| `export-token-strings.py` | ROM → `token-strings.json` (single-byte token spelling table) |
| `export-layout.py` | ROM → `layout.json` (handler records, descriptors) |
| `interp-cells.js` | command-line view of the browser's executable record-cell interpreter |
| `analyze_mathprint_draw_trace.py` | attribute visible LCD mutations to dynamic page `0x34` and pixel-emitter call frames |
| `InspectFunctions.java` | create temporary page-aware function entries and print focused Ghidra decompilation |
| `trace_lcd.py` | replay reset-origin TilEm LCD I/O with its pinned T6A04 model |
| `parity-mathprint.py` | render an expression in TilEm and diff it against the model |
| `export-mathprint-draw-order.py` | export ordered set/clear pixel mutations from hash-pinned TLMT traces |
| `mathprint-trace-report.json` | hashes, exact entry counts, state bytes, and replay results for filled and nested integrals |
| `test-mathprint.js` | fuzz + corpus: every generated expression parses and lays out |
| `render-mathprint.py` | ASCII font/layout dump from ROM |

## Reverse-engineering notes

- `cell-glyph-spec.md` — the `D:E` cell → glyph/token/marker dispatch (`39:4E8E`,
  `39:4F1A`, the `07:44DE` family tables).
- `token-name-spec.md` — ordinary cells → counted strings through `_KeyToString`
  (`01:6D10`, pointer table `01:6E05`).
- `geometry-spec.md` — placement math: `39:683D` cell→pixel, `39:6B1C` fraction
  endpoints, `39:5167`/`5949` row stepping, pen conversion.

## Verification status

`tools/test-mathprint.js` passes 5,018 deterministic parse/layout smoke cases and
checks rectangular boxes plus in-bounds composition marks. It executes the
settled record programs for absolute value, nth root, radical, summation,
`nDeriv(`, and a nested integral/fraction. For each program, the generated final
pixels, visible-changing write order, and complete accepted LCD data-write
stream match independent trace oracles. The complete streams contain 49, 69,
82, 66, 96, and 114 writes, respectively. Captured LCD events are assertion
data, not executor inputs. [confirmed]

The JavaScript path constructs absolute-value, power, $e^x$, $10^x$,
`logBASE(`, radical, nth-root, stacked-fraction, integral, summation, and
`nDeriv(` expressions and numeric matrices from native token bytes. The packed
readers translate the forward scan at `34:58F9`, the backward scan at `34:5911`,
and the 11 lead bytes tested by `_IsA2ByteTok` at `00:1FE8`. The structural
parser translates argument boundaries at `34:5AA3` plus the relevant
`34:594D`, `34:4900`, `34:7393`, and `34:7609` record and metric paths.
[confirmed]

The text field accepts two input paths. Ordinary text uses a preview-specific
semantic frontend; it is not a translation of the TI-OS editor or its
in-progress template AST. A `hex:` prefix supplies space- or comma-separated
native bytes directly to record construction. The raw path reports malformed
streams and untranslated structural types instead of selecting the model
compositor. Both translated paths construct records and LCD writes without
replaying a captured graph or write stream. [confirmed]

Five changed-input regressions start from native byte arrays for summation,
integral, `nDeriv(`, matrix, and a three-level raised fraction. They construct
the settled graph, generate 36–173 accepted LCD data writes, and replay each
byte into the corresponding eight pixels of a 96×64 framebuffer. The tests
pin the complete ordered write streams and packed final framebuffers. These
hashes check deterministic composition; the fresh reset-origin traces below
provide the independent calculator oracles. [confirmed]

The raised-fraction and nth-root encoders add template boundary bytes that the
settled scanner removes before record construction. Retained source buffers pin
the raised-fraction case. The nth-root boundary remains an inferred standalone
encoding because its retained trace does not expose the final source buffer.
[hypothesis]
Fresh reset-origin traces confirm every record field and accepted LCD data write
for three absolute-value cases, four power cases, four exponential cases, four
`logBASE(` cases, eight power/radical composition cases, four nth-root cases,
thirteen fraction cases, twelve integral cases, eleven summation cases, and
twelve `nDeriv(` cases. Six additional fraction-numerator cases cover integral,
summation, and `nDeriv(` numerators, with ordinary and powered bodies.
The trace graph for each of these six cases must decode to the asserted
expression before graph and LCD-write parity is accepted. The fraction cases
also cover structural operands, both recursive nesting directions, and
composition inside radicals and powers.
Five grouping traces additionally cover a flat group, a group containing a
power, a grouped power base, a grouped exponent, and an absolute value whose
body contains a power. Parentheses remain `0x10`/`0x11` leaf tokens. The
renderer routes them through the compound-shape routines at `34:5D1A` and
`34:5D07`, matching every accepted LCD write. The browser does not fetch
`record-programs.json` for generated rendering.
Three structural-composition traces cover `sqrt(X)^2`, `abs(X)^2`, and
`abs(sqrt(X^2+1))`. Their generated graphs match every record field. Their
complete accepted LCD streams contain 35, 33, and 113 writes, respectively.
The structural power-base cases pin the base marker at record offset `+0x0F`
and the exponent's baseline adjustment.
Six named-token traces cover `Ans+1`, `Ans^2`, `sqrt(Ans)`, `X^Ans`, `sin(X)`,
and `sin(sqrt(X))`. The browser decodes the native tokens through the extracted
`01:4252` table and matches every record field plus 49, 40, 63, 32, 56, and 83
accepted LCD writes. Each final 96×64 LCD bitmap also matches the captured
render interval. The opening parenthesis inside `sin(` follows the compound
shape path at `34:5D1A` after `34:6873` receives display code `28h`.
The integral cases cover structural bounds and a nested integral. The
summation cases cover unequal-width limits, structural limits and bodies, and a
nested summation. The `nDeriv(` cases cover unequal-width arguments, structural
bodies, and recursive nesting. Valid `nDeriv(X,X,...)` captures retain `0x58`
in the body leaf; `EF 1E` occurs only in captures with an unfilled template
slot. These cases do not load `record-programs.json` or an LCD event stream.
[confirmed]

Five matrix traces cover $1\times1$, $1\times2$, $2\times2$, $2\times3$,
and $3\times3$ dimensions, unequal column widths, negative elements, and
row-major placement. The constructor matches every record field and child ID.
It also matches 32, 46, 92, 134, and 180 synchronous accepted LCD data writes.
The $2\times3$ capture contains eight additional standard-timer run-indicator
writes at `01:6BBA`–`01:6BFA`; the matrix oracle records both the complete
capture hash and the interrupt-free MathPrint hash. [confirmed]

`parity-mathprint.py` uses LCD trace replay when tracing is enabled. Calculator
parity requires the proprietary ROM. Filled-integral and nested-fraction
results are recorded in
`tools/mathprint-trace-report.json`; the large raw traces stay outside Git.

The preview constructs supported named-token, absolute-value, power, $e^x$, $10^x$,
`logBASE(`, radical, nth-root, stacked-fraction, integral, summation,
`nDeriv(`, and numeric matrix expressions. It exposes every generated accepted
LCD data write in order, including writes that do not change a pixel, and
labels the input source for each timeline. Each timeline row shows the byte
before and after the write, all eight resulting pixel values, and the subset
that changed. The canvas outlines the complete eight-pixel destination span.
Its captured
timeline uses the two retained integral traces and keeps only visible-changing
writes. Every shipped preset has a constructed record program, a nonempty
96×64 accepted-write timeline, and no unresolved operation or empty-template
glyph. Expressions outside the translated grammar use the separately labeled
model output when no generated or captured timeline matches.
[confirmed]

## Regeneration

```sh
python3 tools/export-font.py     # -> font.json
python3 tools/export-token-strings.py  # -> token-strings.json
python3 tools/export-layout.py   # -> layout.json
node tools/test-mathprint.js     # fuzz
python3 tools/parity-mathprint.py  # calc-vs-model parity (needs TilEm + tools/rom.bin)
python3 tools/export-mathprint-draw-order.py \
  integral=/path/to/integral.trace \
  integral_frac=/path/to/integral_frac.trace
```
