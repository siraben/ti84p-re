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
| `layout.json` | page `0x39` class-table records, selected descriptors, and page-`0x07` display-byte tables consumed by translated routines |
| `record-programs.json` | six retained settled-record fixtures used only by offline comparisons |
| `draw-order.json` | accepted visible-pixel LCD mutations from the retained integral traces |
| `tools/mathprint-construction-oracles.json` | fresh settled graphs and accepted-write hashes for independently constructed expressions |
| `tools/mathprint-exponential-logbase-oracles.json` | fresh graph and accepted-write hashes for $e^x$, $10^x$, and `logBASE(` construction |
| `tools/mathprint-matrix-oracles.json` | fresh matrix graphs, result origins, synchronous accepted-write hashes, and interrupt classification |
| `tools/mathprint-grouping-oracles.json` | fresh grouping and nested absolute-value graphs plus accepted-write hashes |
| `tools/mathprint-structural-base-oracles.json` | fresh structural power-base and nested absolute/radical graphs plus accepted-write hashes |
| `tools/mathprint-named-token-oracles.json` | fresh counted-token spelling graphs plus accepted-write hashes in flat, raised, and structural contexts |
| `tools/mathprint-two-byte-token-oracles.json` | fresh list, matrix-name, equation-variable, and string-variable graphs plus accepted-write and framebuffer hashes |
| `tools/mathprint-list-oracles.json` | natural flat and radical-element list graphs, traces, screenshots, and cropped pixel hashes |
| `tools/mathprint-vertical-viewport-oracle.json` | natural depth-four fraction trace, vertical viewport words, accepted-write hash, and exact LCD crop |

`rom-engine.js` translates handler lookup, row-cell emission, direct-glyph and
delimiter classification, the `07:44DE` display-byte remap, `_KeyToString`
index arithmetic, descriptor selection and iteration, fraction endpoints,
class-6 row stepping, and the settled-redraw
point and axis-aligned line wrappers at `34:5D96`–`34:5EA6`. Descriptor-family
selection uses the caller-supplied `flag02` byte for the `ram:025E`/`ram:0254`
bit tests, returns the normalized `0x85E8` kind, and reports an explicit
unresolved result when that state is absent.

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

Structural scan kinds `3` and `4` at `34:5678` now consume the metadata bytes
at `34:59AC` directly. Kind `3` selects one unary child through `34:56E3`.
Kind `4` selects each comma-delimited argument through `34:56EC` and maps
source order to child-record order. The native permutations are integral
`[3,4,1,2]`, `nDeriv(` `[2,1,3]`, `logBASE(` `[2,1]`, and summation
`[4,1,2,3]`. A retained summation trace pins the four kind-`4` calls and their
returned boundaries.

Structural scan kind `6` at `34:568A` now consumes native `06h`–`07h` matrix
containers. It translates the `34:57C2` source-cursor rewind and the following
`34:5AA7` call with `B=20h` for every element. Each returned range ends at a
depth-zero `2Bh` column separator or row-closing `07h`. The raw native path
checks the translated row and column count before constructing the matrix.
Primitive numeric and signed cells are covered by retained value traces. A
retained $2\times2$ trace with `sqrt(2)` and $X^2$ pins the bit-5 parse-ahead
resume path and the record-ID reservation before a structural first cell.

Render-record type `0x22` is translated through `34:622F`. The interactive
integral sign now uses its exact vertical-segment and four-point operation order
instead of stretching glyph `0x08`.

Render-record type `0x20` is translated through its child traversal and rule
emission at `34:620A`. Fractions now draw numerator, denominator, then the
inclusive horizontal rule computed from both child `+7` widths and the parent
`+0x0B` coordinate. Child placement within each record remains open.

Editable generated previews apply both ROM viewport words. `34:5F5D` updates
the horizontal clip from the expression endpoint and cursor width.
`34:5F8B` then updates the vertical clip twice, using the cursor top and the
two live caller paddings. A natural depth-four balanced fraction reaches an
eight-row vertical clip; the translated 17×61 expression crop matches the
calculator exactly. The browser then appends the upper and lower cue bitmaps
from bcall bodies `35:7116` and `35:715B`. Their final 16 accepted writes and
the complete 96×64 LCD match the natural trace and screenshot exactly. The
compact evidence is in
`tools/mathprint-vertical-viewport-oracle.json`.

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

`editorTokenDispatch()` translates the page-39 `39:4A74` token/action class
selection, including the raw `0x3B` exponent-context tests and the `IY+9` bit-0
fraction-context remap, before `39:4C27` handler lookup. The raw `3Dh` measured
template handoff remains a separate result.

`editorArgumentClamp()`, `editorRowFromArg()`, and `editorLayoutArgument()`
translate the arithmetic state at `39:50CF`, `39:5101`, and `39:513E` for
multi-argument editor rows. Their result names the six-row window origin and
the seven-row visible slot; the cross-page continuation remains explicit.

`editorSubexpressionWindow()` and `editorSubexpressionCell()` carry the
`39:4C5A`/`39:4CA4` slot arithmetic into the same state model. They expose the
row-cell base and preserve styled-argument and empty-menu exits without
claiming to implement the surrounding parser walk.

`tools/analyze_mathprint_records.py` replays a full-range TLMT memory snapshot
and writes, then captures 20-byte root/current records only when `34:6105` uses
the render table at `34:6119`. The decoder preserves offset-based field names
until a handler establishes a type-specific meaning. `--graph-json` exports
the final settled record program, its reachable nodes, and a semantic
`expression` tree decoded from their child IDs and payload bytes. Postfix
type-`0x2A` records bind to the expression immediately before their embedded
marker. `EF 1E` remains an explicit extended token because the renderer maps it
to display code `0xF7`, the empty template square. This tree identifies what the
trace contains without inspecting its screenshot. `decodeMathPrintEditorRam()`
also translates the live arena walks at `34:4A83` and `34:4ACE`. It substitutes
the gap payload at the leaf selected by `0x8DC2`, decodes the same record IDs,
and inserts the cursor at `editCursor - editTop`. The browser's generated
record result exposes its graph-derived tree as `settledAst`; the RAM decoder
exposes both cursor-free and cursor-annotated live trees.
`constructEditorExpressionProgram()` converts the cursor-annotated tree back
into the transient type-`0x1F` wrapper, entry leaf, structural records, and leaf
records. It includes the cursor cell in leaf metrics before applying the
structural formulas. The four reset-origin gap oracles round-trip every record
field and reproduce the complete cursor-off LCD bitmap.
`editorInsertPackedToken()` translates ordinary one- or two-byte insertion
through `34:4BB9–4C0D` and `06:4341–4388`. It consumes the decoded live arena,
writes the active leaf payload, and runs the record-graph decoder again. This
regroups delimiters after every byte write instead of preserving the previous
semantic tree. Adjacent root-leaf and fraction-numerator snapshots verify the
resulting cursor AST, every reconstructed record field, and the complete
cursor-off LCD. A five-key `[[1]]` sequence additionally verifies both partial
list frames and the two completed nested-list nodes. The fraction case retains
the structural record's pre-edit `+13h` byte while replacing the `EF 1E`
empty-slot token. Structural templates use the separate mutation path below;
`editorMoveCursor()` handles ordinary and structural boundaries. Live captures
cover every insertable structural type `0x20`–`0x2A` in both directions plus
one depth-two fraction traversal in each direction. The summation captures
combine a type-`0x01` variable, an atomic `EF 1E` empty slot, ordinary children,
and a trailing parent token. Sixteen root-level sequences match every
cursor-dependent layout word. Their reducer also compares the translated LCD
against the real TilEm screenshots outside only the blinking cursor cells.
Two more sequences walk the token-built `[[1]]` matrix across all five packed
tokens in both directions. Two mixed-controller sequences walk a fraction
inside a radical in both directions. Across the 21 additional sequences, 139
RAM states and 118 adjacent moves have exact arena, layout-word, and
masked-screenshot parity. Matrix deletion, row/column edits beyond that
one-cell stream, and other deeper structural combinations remain open.
An eight-state summation construction capture also verifies the type-`0x01`
post-insertion path. Filling the variable automatically selects the lower
bound; filling the other children does not. Packed-token insertion now returns
a decoded arena state that composes directly with the next insertion or cursor
movement. Structural-template insertion returns the same state shape. The
blank-root summation constructor therefore feeds the entire seven-key fill and
exit sequence without importing an intermediate calculator state.
`editorInsertStructuralTemplate()` translates fraction insertion from source
token `EF 2E` at every cursor class in the root leaf and both child leaves of
one outer fraction, plus the blank radicand of one prefixed radical. A
populated leaf moves its left payload into the new numerator and retains its
right payload after the six-byte marker. The shared one-child path translates
absolute value (`B2`), $e^x$ (`BF`), $10^x$ (`C1`), and radical (`BC`)
insertion. Four $e^x$ captures cover every root cursor class; blank captures
exercise the other two added kinds. Radical insertion covers every cursor
class in the root leaf, both children of one outer fraction, and the radicand
of one prefixed radical. A one-child insertion leaves the left segment in its
parent and replaces one packed token to the cursor's right; a captured `5D 00`
list token proves the two-byte boundary. A structural marker to the right is
retained instead. Seven natural captures exercise that rule for the one-child,
nth-root, power, log-base, integral, nDeriv, and summation constructor paths.
Integral source token `24` selects type `0x22`. It creates lower-bound,
upper-bound, body, and variable children, then selects the lower bound. Payload
left of the cursor remains in the parent. Leading and mid-leaf insertion replace
one packed token to the cursor's right. Four reset-origin captures cover every
root cursor class.
nDeriv source token `25` selects type `0x23`. It creates variable, body, and
evaluation-value children, then selects the variable. The live blank variable
adds a two-pixel body gap and uses a solid focus box when repeated after the
evaluation bar. Four reset-origin captures cover every root cursor class.
Summation source token `EF 33` selects type `0x29`. It creates variable, lower,
upper, and body children, then selects the variable. Four reset-origin captures
cover every root cursor class and preserve the constructor's child order. The
returned decoded arena matches every captured post-key record field, not only
the cursor-annotated expression.
Nth-root source token `F1` selects type `0x24`. A blank root receives `Ans` in
the index and an empty radicand. Leaf-end and mid-leaf insertion migrate the
left payload into the index. Leading insertion creates two empty children and
selects the index. Leading and mid-leaf insertion replace one packed token to
the cursor's right. Four reset-origin captures cover every root cursor class.
Log-base source token `EF 34` selects type `0x28`. It creates empty base and
argument children and selects the base. Payload left of the cursor remains in
the parent. Leading and mid-leaf insertion replace one packed token to the
cursor's right. Four reset-origin captures cover every root cursor class.
Postfix-power source token `F0` selects type `0x2A`. Blank insertion supplies
`Ans` as the base. Leaf-end and mid-leaf insertion bind the atom to the cursor's
left. Leading insertion creates an editor-only empty base and replaces the
packed token to the cursor's right. Settled decoding rejects an empty power
base after the live editor state ends.
At `34:4900`, unnamed bcall ID `53ADh` inserts the new record at the old entry
boundary. Initialization through `34:4928` skips physical byte `+13h`, so the
new structural record retains that byte from the old entry record. A nested
radical and fraction below a root `3` retain `33h`; the value is not a depth
proxy or the active child's first byte.
The function consumes the decoded arena because new record IDs,
structural-depth bytes, and retained child selectors are not present in the
semantic tree alone. Sixty cursor-class transitions and seven
template-before-fraction transitions verify markers, controller states, cursor
ASTs, every reconstructed record field, and complete LCD output. Deeper
structural positions beyond the captured outer fraction and radical remain
separate.
`editorMovePackedTokenCursor()` translates ordinary in-leaf LEFT and RIGHT
movement. A reset-origin `12` capture verifies the end, middle, and returned
cursor states. The middle state also establishes that a cursor before existing
payload overlays the following cell and adds no width; only a leaf-end cursor
allocates a new cursor cell. The transition keeps two-byte native tokens
indivisible. Navigation across a structural record marker remains separate.
`editorDeletePackedToken()` translates DEL at the right edge of the gap. Root
and fraction-numerator transitions verify one-byte deletion, record
reconstruction, and complete LCD output. When the active leaf becomes empty,
the translated `34:4549–455B` path restores `EF 1E` and leaves the cursor before
that square. Two-byte deletion is kept atomic. Structural-record deletion
uses a separate decoded-arena path.
`editorDeleteStructuralTemplate()` translates deletion from an `EF 1E` child.
One-child types remove the containing six-byte marker, structural record, and
child leaf. Fraction and nth-root types promote the sibling payload in either
direction. Integral, nDeriv, log-base, and summation retain a blank child.
Nine reset-origin transitions verify the distinct cursor trees, meaningful
record fields, and all 768 LCD bytes. Finite dispatch tests cover every
insertable type from `0x20` through `0x2A`. A nested fraction-in-radical case
verifies that deleting the inner template restores `EF 1E` in its parent leaf.
Other nested deletion states, matrix type `0x2B`, and structural-boundary
deletion remain open.
The analyzer selects the first post-key `34:660A` entry at the shallowest Z80
stack depth. The exporter pairs
parent/index observations at `34:6CCD` with the resolved child ID and record
pointer at `34:6CD8`, so the export includes structural records, leaf records,
and leaf payload bytes beginning at `+0x13`. The ordered `dispatches` array
retains secondary structural passes constructed while rendering a leaf, such
as an exponent or nested fraction. An `EF type id_lo id_hi` payload sequence
references one of those structural records. Each dispatch also records the
live logical origin at `ram:8DFE`/`ram:8E00`. The translated editor keeps it
separate from the physical screen origin bytes at `ram:8DFA`/`ram:8DFB`.

`app.js` is organized in sections: box primitives → layout constructs → text runs
→ expression parser → canvas rendering → UI. A "box" is `{rows, baseline, marks,
adv}`; `adv` (pen advance) is separate from bitmap width so glyphs can overhang.
For a closed expression accepted by the native constructor, model rows and marks
come from the translated settled record graph and primitive stream. Partial,
unsupported, and over-wide input keeps the lenient compositor so editing remains
visible while the settled path reports its exact construction boundary.

`rom-engine.js` exposes the closed editor helpers separately from the settled
record executor. `editorAdvanceArgument()` and `editorRetreatArgument()`
translate forward and reverse slot movement at `39:5167` and `39:523B`. They
preserve the asymmetric two-row overflow guards, styled scroll sequences, and
saved-search carry exits. Their `savedOperandState` input supplies the OP
buffers and one logical or raw VAT snapshot. The F2 and E7 wrapper outcomes
are derived in call order; a missing state leaves the saved-F2 branch explicit.
Scroll calls remain ordered effects rather than generated pixels.
`editorAlphaSearch()` closes the page-39 dispatcher around `_FindAlphaUp` and
`_FindAlphaDn`. It translates the ascending/descending class-2 paths, the
`39:5C2E` special-class check, the `39:1942`/`A=06` repeat, and carry exits from
the fixed-bank `00:3A53`/`00:306F` dispatchers. The caller supplies OP1 and a
logical VAT snapshot; the model derives every page-7 result and the
protected-program repeat from that state.
`editorFindAlphaVat()` translates the page-7 nearest-name selection over an
explicit logical VAT snapshot. It applies the ROM's type aliases and OP-name
byte ordering, returns OP1/OP3 and the selected VAT pointer, and reports carry
at either alphabetic endpoint. `editorDecodeAlphaVatRegion()` derives entries
from raw 64 KiB RAM using the fixed and length-prefixed strides at
`07:511F`–`07:51FD`. `editorDecodeAlphaVatSnapshot()` reads `pTemp` and
`progPtr`, selects the named/list or fixed-token region, and supplies the
logical snapshot accepted by `editorAlphaSearch()`.
`editorFirstArgumentAction()` and `editorAdvanceAction()` translate the
action-`0x03` and action-`0x04` controllers at `39:51F1` and `39:52A5`. They
retain byte-counter wrap and the action-`0x04` one-call exit at `39:52B6`.
`settledRecordAllocationGeometry()` decodes the fixed and matrix-dependent
allocation rows at `33:4F42`–`33:4F81`.
`settledRecordAllocationCapacity()` translates the conditional reserve,
record-tail, and requested-byte subtractions at `34:4B7C`–`34:4B9D`, including
their 16-bit wrap and the allocator carry return at `34:486F`.
`settledRecordAllocationCheck()` wires the page-33 geometry request into that
gate through the `34:4862` caller, preserving the record type and matrix count
as constructor inputs while leaving the record-list arena words explicit.

## Tooling

| Tool | Purpose |
|------|---------|
| `export-font.py` | ROM → `font.json` (glyph data for the renderer and its font-table tab) |
| `export-token-strings.py` | ROM → `token-strings.json` (single-byte token spelling table) |
| `export-layout.py` | ROM → `layout.json` (handler records, descriptors, and page-7 display-byte tables) |
| `interp-cells.js` | command-line view of the browser's executable record-cell interpreter |
| `analyze_mathprint_draw_trace.py` | attribute visible LCD mutations to dynamic page `0x34` and pixel-emitter call frames |
| `InspectFunctions.java` | create temporary page-aware function entries and print focused Ghidra decompilation |
| `trace_lcd.py` | replay reset-origin TilEm LCD I/O with its pinned T6A04 model |
| `parity-mathprint.py` | render an expression in TilEm and diff it against the model |
| `export-mathprint-draw-order.py` | export ordered set/clear pixel mutations from hash-pinned TLMT traces |
| `mathprint-trace-report.json` | hashes, exact entry counts, state bytes, and replay results for filled and nested integrals |
| `test-mathprint.js` | fuzz + corpus: every generated expression parses and lays out |
| `test-mathprint-browser.spec.js` | headless Chromium check for input entered during delayed asset loading and repeated horizontal overflow |
| `cachebust-mathprint.py` | content-version the built page's JS, JSON, and CSS references for each preview deployment |
| `render-mathprint.py` | ASCII font/layout dump from ROM |

## Reverse-engineering notes

- `cell-glyph-spec.md` — the `D:E` cell → glyph/token/marker dispatch (`39:4E8E`,
  `39:4F1A`, the `07:44DE` family tables).
- `token-name-spec.md` — ordinary cells → counted strings through `_KeyToString`
  (`01:6D10`, pointer table `01:6E05`).
- `geometry-spec.md` — placement math: `39:683D` cell→pixel, `39:6B1C` fraction
  endpoints, `39:5167`/`5949` row stepping, pen conversion.

## Verification status

`tools/test-mathprint.js` passes 5,019 deterministic parse/layout smoke cases and
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

Raised operands use the packed-token classifier at `34:580C`. Its caller-scoped
domain contains 3,047 states after the numeric and `EF1Eh` paths are removed.
Direct letters, `Ans`, list, matrix, and string names, `π`, `BB31h`, and the
bounded `5Fh`/`EBh` name forms follow the ROM comparisons. The bounded loop
accepts only `30h`–`39h` and `41h`–`5Bh`, with limits of eight and five bytes.
The parser keeps the designator and accepted name bytes in one atom. [confirmed]

The text field accepts two input paths. Ordinary text uses a preview-specific
semantic frontend; it does not drive the translated TI-OS editor state machine.
A separate ROM-derived decoder reads captured live editor RAM, including its
active gap leaf and cursor. The ROM engine can advance that state through an
ordinary packed-token insertion, root leaf-end fraction-template insertion,
in-leaf cursor move, packed-token deletion, or the captured structural-deletion
classes, but the browser does
not yet expose the mutation API as an interactive calculator editor. A `hex:`
prefix supplies
space- or comma-separated native bytes directly to record construction. The
raw path reports malformed
streams and untranslated structural types instead of selecting the model
compositor. Both translated input paths construct records and LCD writes
without replaying a captured graph or write stream. [confirmed]

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
Two native-list traces cover `{1,2}` and `{sqrt(2),1}`. The parser preserves
`08h`/`09h` element boundaries in semantic list nodes. The renderer follows the
brace paths at `34:5E0F` and `34:5E14`; the waist aligns with the enclosed
baseline. Both generated cropped bitmaps match the calculator exactly. Nested
lists and structural elements use the same native-byte constructor.
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
Changed-input regressions also construct direct `X^Y`, `X^Ans`, `X^L1`, and
`X^(BB31h)` streams. Each generated accepted LCD write expands to its eight
pixel results and replays to the generated final framebuffer.
The long-input regression
`int(1,3,(1//2)X,X)+int(1,3,(1//2)X,X)` constructs both integral records and a
106-pixel expression endpoint. The editor viewport translation applies the
17-pixel horizontal clip observed at `ram:8E02`, then appends the left-overflow
bitmap from `34:60B8`. Its 198 accepted writes match the natural calculator
redraw after removing the separate eight-write auxiliary right-side stream.
The calculator
trace remains a comparison oracle; the browser computes the record graph,
viewport state, bitmap operation, and LCD writes from translated logic.
Radical and nth-root hooks enter `34:6C37` through `34:630C`. The five-pixel
bitmap header therefore uses the same `34:6C5F` display-unit gate as a glyph.
An anchor left of `ram:8E02` skips the complete hook while the stem and
vinculum retain their separate line paths. The natural oracle in
`tools/mathprint-radical-viewport-oracles.json` pins the carry branch and final
pixel result.
The generated frontend also exercises three-way and mixed nested expressions
with endpoints above 130 pixels. It rejects record metrics that exceed the
unsigned 16-bit fields used by `34:7393` and `34:7609`, while model mode remains
available for partial input during editing. Model mode keeps the complete
composition on a horizontally scrollable canvas and reports the model endpoint,
96-pixel LCD overflow, and translated editor clip separately from the settled
record view. Text input retains this model when the settled constructor rejects
an over-wide record, and reports the constructor error beside the model timeline.
Its heuristic extent is therefore a readability aid, not a second LCD oracle.
Live input also carries the previous clip word between edits. The browser tests
the translated retain, reset, and regrow branches, then extends the same path to
eight repeated integrals with a 442-pixel record and 127 native token bytes. The
textarea grows with wrapped input until its capped editing height, so long source
text remains accessible independently of the 96-pixel LCD viewport.
The integral frontend accepts `int(`, `integral(`, and the ROM token
spelling `fnInt(` as aliases for the same `EF24h` structural record.
The one-argument hyperbolic functions `sinh(`, `cosh(`, and `tanh(` use their
decoded single-byte ROM tokens and the same translated argument-boundary path
as the circular trigonometric functions.
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
