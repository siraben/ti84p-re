# Equation display (MathPrint)

MathPrint is the OS subsystem that turns a tokenized expression into a two-dimensional
screen layout. It is used by the homescreen entry line, the Y= editor, the Solver
equation line, and the template menus. Page `39` handles template editing and
record selection. The live editor and settled homescreen redraw traverse
display objects on page `34`. Both paths drive the services described in
[Display and LCD](display-lcd.md).
It consumes the token stream described in [Tokenizer & TI-BASIC](tokenizer-basic.md)
and preserves the OP registers described in [Floating-point engine](floating-point.md).

The editor path is a cell-grid typesetter. The OS classifies each token, selects
a compact handler record, walks the expression into rows and slots, maps each
cell to pixel coordinates, and emits glyphs or graph-buffer rules. A page `34`
object walker redraws the record graph through page `01` glyph output and page
`04` line and point routines. [confirmed]

```mermaid
flowchart TD
    token["Token or template action"] --> dispatch["39:4A74<br/>class selection"]
    dispatch --> table["39:4C27<br/>class table 39:5E45"]
    table --> record["handler record<br/>rows, actions, cells"]
    record --> operand["39:5167<br/>recursive operand walker"]
    record --> cell["39:4E8E<br/>cell emitter"]
    record --> geom["39:69C8<br/>descriptor/fraction geometry"]
    operand --> dispatch
    geom --> coord["39:683D<br/>cell to pixel coordinate"]
    coord --> cell
    cell --> glyph["07:4588 / 01:6293<br/>glyph output"]
    geom --> rules["39:6ABF / ram:3555<br/>rules and rectangles"]
```

The diagram shows the page `39` editor path. It does not describe the page `34`
record-graph walker. [confirmed]

## Editor state and record graph

MathPrint keeps native token bytes in an editor gap buffer and maintains a live
arena of numbered records. Page `39` treats the active expression as token
classes, handler rows, argument slots, and packed `D:E` display cells. The
class table at `39:5E45` contains 68 entries. Sixty-six entries point to decoded
handler records; the class-`0x00` pointer does not decode as a page `39`
handler, and class `0x13` has a null pointer. [confirmed]

Page `34` allocates the record arena while the editor is active. A leaf record
contains a token program. A structural record contains a fixed header followed
by child record IDs. `34:4ACE` walks the structural region, and `34:4A83` walks
the leaf region. `34:4AAF` substitutes the active gap-buffer payload when the
leaf pointer equals the word at `0x8DC2`. The record graph therefore preserves
the editable equation tree before evaluation; page `39` row and cell state is
the transient layout view of that live equation. [confirmed]

```mermaid
flowchart LR
    tokens["Native token bytes"] --> gap["Editor gap buffer<br/>active leaf bytes"]
    gap --> editor["Page 39 layout state<br/>classes, rows, slots, D:E cells"]
    gap --> scan["34:58F9 / 34:5A99<br/>token and argument scans"]
    scan --> build
    build["34:4900 record allocation"] --> graph["Live record arena<br/>leaf programs + structural child IDs"]
    gap --> substitute["34:4AAF<br/>active-leaf substitution"]
    substitute --> graph
    graph --> metrics["34:7393 / 34:7609<br/>metrics and geometry"]
    metrics --> render["34:6105 / 34:660A<br/>record and leaf rendering"]
    render --> primitive["Page 1 / 4 / 7<br/>glyphs, points, and lines"]
    primitive --> lcd["Accepted LCD data writes"]
```

The record graph decodes as an expression tree because structural child IDs
preserve argument order. The handler records describe how an editable token
class is laid out; they do not by themselves encode one whole equation tree.
[confirmed]

## Core state

The layout engine keeps most of its state in `0x85DE`–`0x85F2`. The table below names the
fields that matter for reading the page `0x39` code. [confirmed]

| RAM | Role | Meaning |
|-----|------|---------|
| `0x85DE` | mode / class | Caller mode at entry, then the current layout class. |
| `0x85DF` | row index | Current row inside the selected handler or template. |
| `0x85E0` | slot index | Current argument or cell slot. |
| `0x85E1` | row count | Number of rows in the current handler record. |
| `0x85E2` | slot count | Number of cells or arguments in the active row. |
| `0x85E3`–`0x85E6` | saved display state | Snapshot of shared display flags while the engine redraws. |
| `0x85E7` | OP scratch | Saved `OP1` slot used while recursing into operands. |
| `0x85E8` | template kind | Low nibble selects descriptor-backed template UI. |
| `0x85E9/0x85EA` | descriptor origin | Packed pixel base used by descriptor cell mapping. |
| `0x85EB` | row height | Pixel height for the current descriptor row. |
| `0x85EC/0x85ED` | cell pointer | Pointer to descriptor cell data. |
| `0x85EE/0x85EF` | fraction geometry | Measured numerator/denominator cell counts for fraction templates. |
| `0x85F2` | OP scratch | Second saved `OP1` slot. |
| `0x86D7/0x86D8` | pen coordinate | Pixel coordinate staged before graph/small-font output. |
| `0x844B/0x844C` | text row/column | Shared OS cursor row and column; `844C` also participates in overflow. |
| `0x984A` | baseline row | The row restored around recursive operand emission. |
| `0x9D27` | saved geometry | Copy of the measured fraction geometry used by the template handoff. |

The main draw/measure distinction comes from `(IY+0x36)` bit 6. Clear means the engine is
measuring or preparing state; set means it may emit pixels. Several other `IY` flags bias
class selection: `(IY+0x09)` bit 0 selects fraction/argument context, while `(IY+0x02)`
bits 4, 5, and 6 select exponent and alternate edit forms. [confirmed]

## Handler records

A visible expression is driven by handler records reached through the class table at
`39:5E45`. Each class has one word entry:

```text
handler = word(39:5E45 + 2 * class)
```

Most entries point to compact data, not executable code. The common record format is a
variable-length tail:

```c
typedef uint16_t EqDispCell;  /* high byte D, low byte E */

typedef struct {
    uint8_t row_count;
    uint8_t cell_count[];  /* row_count entries */
    /* uint8_t row_action[row_count]; */
    /* EqDispCell cell[sum(cell_count[0..row_count - 1])]; */
} EqDispHandlerRecord;
```

`row_action[]` bytes are row labels or control actions. They are separate from the cell
stream. The row-cell pointer routine at `39:4DCA` skips the row count, the per-row cell
counts, and the row-action bytes before it reaches the packed two-byte cells. The cell
emitter at `39:4DE6` then walks the selected row and calls `39:4E8E` for each `D:E` cell. [confirmed]

Examples:

| Class | Record | Meaning |
|-------|--------|---------|
| `0x08` | `39:608B` | Numeric-calculus operator row, including `nDeriv(` and `fnInt(`. |
| `0x0D` | `39:60F9` | Fixed structural glyph rows, including direct `Lintegral` cells. |
| `0x29` | `39:6546` | Group/root-family control row. |
| `0x2A` | `39:654D` | Root/power row containing the `00 10` payload cell. |
| `0x30` | `39:6030` | Fraction-context variant of the class-`0x08` operator row. |
| `0x31` | `39:6433` | Stacked root/power row with a degree row. |

The display cell `00 C8` is the visible `fnInt(` name. It appears in class `0x08` and
class `0x30`; it is distinct from the fixed `Lintegral` glyph cells in class `0x0D`. [confirmed]

## Settled record graph

Every settled record begins with this 20-byte header. The word names remain
address-based where different render types assign different meanings. [confirmed]

```c
#pragma pack(push, 1)
typedef struct {
    uint16_t id;          /* +00h: arena ID */
    uint8_t type;         /* +02h: leaf/object or structural render type */
    uint16_t word03;      /* +03h: parent ID in captured constructed records */
    uint16_t word05;      /* +05h: leaf height or structural child selector */
    uint16_t word07;      /* +07h: type-specific height or width */
    uint16_t word09;      /* +09h: type-specific width */
    uint16_t word0B;      /* +0Bh: local x origin for recursive entry */
    uint16_t word0D;      /* +0Dh: local y origin or type-specific anchor */
    uint16_t word0F;      /* +0Fh: type-specific flags or depth state */
    uint16_t word11;      /* +11h: payload length or dimensions/depth */
    uint8_t byte13;       /* +13h: first payload byte or type-specific data */
} SettledRecordHeader;
#pragma pack(pop)
```

Leaf types below `0x1F` store `word11` payload bytes beginning at `+0x13`.
Structural types `0x1F`–`0x2B` retain the complete header and append
little-endian child IDs at `+0x14`. `34:6CCD` resolves a child ID through
`34:4B05` and `34:4A83`; the child words are not pointers. Captured construction
writes place the parent record ID at `+3`. [confirmed]

A leaf payload is also a small record program. The sequence
`EF type id_lo id_hi` invokes a structural record. `EF 2D` closes or separates
that embedded object without drawing a glyph. Ordinary native token bytes stay
in program order around those markers. A power record of type `0x2A` binds the
preceding leaf run as its base and child 1 as its exponent. [confirmed]

Construction uses three ROM table families. `34:594D` maps 16 source-token
pairs to render types. `34:59AC` gives one five-byte scan row for each type
`0x1F`–`0x2B`. `33:4F82` gives the corresponding allocation geometry. The
metric and geometry passes dispatch the same 13-type domain through `34:739F`
and `34:7611`. [confirmed]

`33:4F6D` also decodes the three-byte allocation rows at `33:4F82`. It returns
the workspace request in `DE`, the child-slot count in `BC`, and the record
size in `HL`. For example, the type-`0x22` integral row returns 112 workspace
bytes, four child slots, and 28 record bytes. Type `0x2B` derives all three
values from its matrix element count at `33:4F42`–`33:4F6C`. [confirmed]

`34:4869` passes that workspace request to the capacity gate at
`34:4B7C`. `34:4B86` starts with the word at `0x8DB1`. When
`(IY+2Dh).0` is clear, it subtracts the conditional reserve at `0x8DF8`; when
the bit is set, it skips that subtraction. It then subtracts the record tail
at `0x8DBE`. Each subtraction follows `OR A`, so it starts with carry clear and
wraps as a 16-bit word. A borrow from the record-tail subtraction makes
`34:4B80` skip the request comparison. Otherwise `34:4B82` subtracts the
requested bytes. Either carry returns from the allocator caller at `34:486F`
with `A=0x02`; an exact fit continues with zero bytes remaining. [confirmed]

The finite capacity model partitions all $2^{65}$ combinations of four input
words and the reserve-gate bit into six paths. A 524,287-state raw-byte
differential basis covers each word value at the range and request boundaries.
The initial values of `0x8DB1`, `0x8DBE`, and `0x8DF8` still depend on the
calling editor state, so this gate alone does not define one source-character
limit for every home-screen expression. [confirmed] for the gate and projected
model; [hypothesis] for a context-independent character limit.

`settledRecordAllocationCheck()` translates the closed caller ABI at `34:4862`:
it obtains the workspace request from the type/matrix geometry row and passes
that request to the capacity gate, retaining the allocator's `A=02h` carry
return. The arena words remain explicit because their producers walk the
record list at `34:4A83`/`34:4ACE`; this boundary is therefore a stateful input
rather than a fabricated free-space estimate. [confirmed]

The structural children preserve semantic argument order after the source scan
applies the metadata permutation. For example, the integral metadata is
`04 03 04 01 02`: scan kind 4 reads four source arguments and assigns them to
children 3, 4, 1, and 2. The settled graph then stores lower endpoint, upper
endpoint, body, and variable in the order consumed by the type-`0x22` renderer.
[confirmed]

## Token classification

`eqdisp_dispatch_token` (`39:4A74`) turns an incoming token or action byte into a layout
class. It first handles the special `0x3D` template handoff, then applies context bias. [confirmed]

```pseudocode
\begin{algorithm}
\caption{Class selection}
\begin{algorithmic}
\REQUIRE incoming byte $a$
\IF{$a = \mathtt{0x3D}$}
  \STATE jump to the template handoff at \texttt{39:672E}
  \RETURN
\ENDIF
\STATE $c \gets a - \mathtt{0x2A}$
\IF{exponent/edit-context flags select an alternate form}
  \STATE bias $c$ into the alternate class family
\ENDIF
\IF{fraction or argument context is active and $c \in \{3,4,5,6,7,8\}$}
  \STATE $c \gets c + \mathtt{0x28}$
\ENDIF
\STATE $\mathtt{85DE} \gets c$
\STATE $HL \gets \mathrm{word}(\mathtt{39:5E45} + 2c)$
\end{algorithmic}
\end{algorithm}
```

This is why the same token can render differently in ordinary and stacked contexts. For
example, class `0x08` and class `0x30` share the `fnInt(`/`nDeriv(` operator family, but
`0x30` is selected after the fraction-context bias. [confirmed]

## Layout pass

The high-level loop is:

1. Save display and OP state.
2. Classify the current token into `0x85DE`.
3. Load the handler record from `39:5E45`.
4. Measure row and slot counts into `0x85E1/0x85E2`.
5. Recurse into argument slots when a handler cell represents an operand.
6. Restore the baseline row and emit visible cells during the draw pass.

The static caller graph assigns multi-argument walking to `39:5167`. When
selected, it keeps the argument index in `0x85E0` and uses `0x85E2` as the
argument count. Forward paths pass saved OP1 state through `39:59E0`; reverse
paths use `39:59F9`. These routines dispatch `_FindAlphaUp` and `_FindAlphaDn`
on page 7, respectively; they do not dispatch a parser-stream scanner.
[confirmed] `_FindAlphaUp` and `_FindAlphaDn` scan the physical VAT and retain
the nearest alphabetic successor or predecessor. The result does not depend on
the physical order of VAT records. [confirmed]

For `fnInt(expr,var,lower,upper[,tol])`, the visible MathPrint fields preserve parser
order: slot 0 is the integrand, slot 1 is the variable, slot 2 is the lower endpoint,
slot 3 is the upper endpoint, and slot 4 is the optional tolerance. The evaluator on
pages `02` and `33` consumes the same order. [confirmed]

The same routine implements tall-template row composition. `eqdisp_layout_main` reaches
`39:5167` from the action-`0x08` window-advance path at `39:50A4` and the action-`0x04`
single-step path at `39:52B3`. `39:5167` calls `39:5949` to decide whether the next argument
consumes one or two display rows, adjusts `0x844B`, emits slot markers through `39:4E0A`,
and emits the saved operand through `39:5B10` or `39:5B1D`. These bytes define
row composition around fixed structural cells. The filled and nested-integral
traces below do not select this entry. [confirmed]

Action `0x03` enters `39:51F1`. A nonzero argument index dispatches to the
reverse walker at `39:523B`. At index zero, bit 0 of `(IY+1Dh)` selects the
row-token tail. A clear bit with fewer than eight arguments enters the
do-while loop at `39:50A1`. The loop calls `39:5167` once per count value; a
zero count decrements through `0xFF` and therefore makes 256 calls. Counts of
eight or more set the index to `count - 1`. The path computes the first
visible slot as `count - 8 + baseline` with byte arithmetic. `39:4DCA`
looks up the current handler row from `0x85DF`; `39:4CA4` then emits the suffix
beginning at the computed slot. The path emits the final argument on row 7
through `39:4E14`. [confirmed]

Action `0x04` enters `39:52A5` and computes
`((count - 1) - index) & 0xFF` once. A nonzero result calls `39:5167`. The jump
at `39:52B6` then targets `39:52A2`. The delegated walker returns through
`39:5447`, and the outer path enters that row-token tail again. Only an
initially zero result reaches the bit-0 test on `(IY+1Dh)`. A set bit selects
the same tail. With the bit clear, the zero comparison leaves `A=0`, so the
jump to `39:513E` lays out argument zero. [confirmed]

## Cell coordinates

Descriptor-backed templates use a fixed ABI. A descriptor is:

```c
typedef struct {
    uint16_t base_yx;       /* packed base y/x coordinate */
    uint16_t box_yx;        /* packed box y/x coordinate */
    uint8_t  row_height;
    uint16_t cols_rows;     /* packed column/row count */
    uint16_t cell_pointer;  /* pointer to descriptor cells */
} EqDispTemplateDescriptor;
```

The mapper at `39:683D` converts a descriptor cell to pixels. The `+7` loop (`DEC B; ADD A,7`)
builds the *high* byte and the `+(rowHeight+2)` loop builds the *low* byte; the caller stores
`HL` to `penCol`(`0x86D7`, low→x) / `penRow`(`0x86D8`, high→y), so the two products land as:

$$
\begin{aligned}
x &= \mathit{base}_x \\\\
  &\quad + \mathit{row}\,(\mathit{rowHeight}+2).
\end{aligned}
$$

$$
y = \mathit{base}_y + 7\,\mathit{col}.
$$

The known descriptors are:

| Descriptor | Kind | Use |
|------------|------|-----|
| `39:686F` | `0x10` | Fraction menu descriptor. |
| `39:6880` | `0x11` | Root/function template menu descriptor. |
| `39:6893` | descriptor family | Two-row template descriptor. |
| `39:689C` | descriptor family | Two-row, six-column descriptor. |
| `39:68A5` | descriptor family | Two-row, three-column descriptor. |

For kind nibbles `3` and above, `39:69C8` adds `0x10` and calls
`ram:025E` (`BIT 6,(IY+2); RET`). A set bit selects `39:689C`. Otherwise it
adds `0x10` again and calls `ram:0254` (`BIT 5,(IY+2); RET`); a set bit selects
`39:68A5`, and a clear result selects `39:6893`. The JavaScript
`selectDescriptor` translation takes this caller-owned `flag02` byte explicitly
for the family branches and reports the byte that `39:69FC` stores back at
`0x85E8`. [confirmed]

Descriptor `39:6880` contains `FE09`, `FB C8`, `00 C7`, `00 C8`, and `FB C7` in one row.
That places `fnInt(` as a menu/template cell, not as a structural integral glyph. [confirmed]

## Fractions

Fractions are the most completely recovered dynamic template. The kind-2 fraction path
uses `0x85EE` and `0x85EF` as measured numerator and denominator widths. It draws a fixed
template box, emits the row/column labels, and updates the focused numerator or denominator
cell. [confirmed]

The rectangle helper at `39:6ABF` handles the focus rectangle. Its endpoint helper at
`39:6B1C` uses:

$$x_\text{left} = \mathtt{0x1B} + 7n$$

$$x_\text{right} = x_\text{left} + 4$$

Static callers of `39:6ABF`, `39:6B1C`, and the box wrapper `39:6AF5` are all in this
fraction-template UI path. The emitter for the visible bar in a generic
expression remains unidentified. [confirmed]

## Exponents and raised rows

Superscripts are represented as row placement, not as a font attribute. The helper at
`39:4CE9` raises classes in the `0x24`–`0x28` family and class `0x39` by forcing `0x844B`
to a higher display row before emitting the selected cell. The per-row height accounting
then folds that raised row into the parent layout. [confirmed]

This means `X^2` is stored and walked as ordinary cells in different rows. The row selection
does the work; the glyph for `2` is the ordinary one.

## Radicals

The large-font table contains the fixed `Lroot` glyph (`0x10`) at `07:466F`.
The root/power records also contain the payload cell `00 10` in classes `0x2A`
and `0x31`. These facts do not establish a direct emission path between the
cell and that glyph. [confirmed]

The same records also contain low-byte `E=1F` cells for related power/root pieces. Those
cells follow the ordinary token-string path; they are not the special high-byte `D=1F`
cell form used by the `39:4E8E` IX-backed branch. [confirmed]

The direct mapper at `39:4F1A` does not accept `00 10`. If that cell follows the
ordinary string path, `_KeyToString` selects `All+`, not `Lroot`. The final
root-mark emitter must therefore be selected by an upstream or dynamic path
that remains unidentified. [hypothesis]

The static `39:5167` path can advance a recursive operand window when selected,
but the demonstrated traces do not connect it to the radical records. The
precise division between fixed root glyphs, radicand placement, and any
vinculum drawing remains open.

## Integrals and summations

The visible `fnInt(` menu cell and the structural integral glyph are separate things.

| Concept | Cell / glyph | Source |
|---------|--------------|--------|
| `fnInt(` display name | `00 C8` | Class `0x08`/`0x30` operator records and page-1 token-name strings. |
| Fixed integral glyph | `Lintegral` `0x08` | Class `0x0D` cells `FC3F` and `08 42`, emitted through `39:4F1A`. |
| Summation glyph | `0xC6` family | Fixed glyph data; no direct `00 C6` page `0x39` handler cell has been found. |

The fixed `Lintegral` glyph is emitted by the ordinary structural-glyph path:
`39:4E8E` calls the delimiter classifier, falls through to `39:4F1A`, maps the cell to
large-font code `0x08`, and emits it. [confirmed]

The static `39:5167` path can compose argument slots around a fixed glyph:

1. Place the tall integral glyph on the main axis.
2. Walk the lower, upper, integrand, and variable slots in parser order.
3. Update `0x844B` by the row step from `39:5949`.
4. Emit slot markers through `39:4E0A`.
5. Emit the operand bodies through `39:5B10` and `39:5B1D`.

The parser slot order and the static compositor are identified. The filled and
nested-integral traces use `39:4CA4` instead, so the expression or cursor state
that selects `39:5167` remains open. Fixed glyph cells use `39:4E8E` and
`39:4F1A`; page `07:4588` copies large-font records. [confirmed]

## Delimiters

The fixed delimiter families are handler records. Classes
`0x17`, `0x18`, and `0x19` point to one-row records at `39:62C8`, `39:62DF`, and
`39:62F6`. Each record contains ten cells. Page 7 maps those cells to output families
`61 00`–`61 09`, `60 00`–`60 09`, and `AA 00`–`AA 09`. [confirmed]

This covers the fixed delimiter surface. The delimiter families remain fixed
handler records and page `0x07` display-byte mappings. A runtime path that
selects their height remains unidentified. [confirmed]

## Emission paths

Cells reach pixels through a small set of output paths:

| Path | Entry | Use |
|------|-------|-----|
| Generic cell emitter | `39:4E8E` | Dispatches two-byte display cells. |
| Direct large glyph map | `39:4F1A` | Maps `FC3C`–`FC40`, `FE7D`–`FE81`, and `xx42` cells to large-font codes. |
| String path | `39:6B66` + page `01:6D10` | Converts ordinary token cells to counted strings. |
| Display-byte remap | page `07:44DE` | Remaps `FE`, `FC`, and `FB` prefixed display bytes. |
| Small-font blit | page `01:6293` | `_VPutMap`; emits small labels and compact limits from `0x86D7`. |
| Large-font blit | page `07:4588` | Copies one fixed large-font glyph record. |
| Rule / rectangle helpers | `39:6ABF`, `39:6AF5`, `ram:3555` | Draw fraction UI rectangles, boxes, and fixed chrome lines. |

The page-7 large-font service copies fixed glyph rows. It does not measure a radicand or
stretch a glyph by itself. [confirmed]

## Algorithm summary

```pseudocode
\begin{algorithm}
\caption{MathPrint layout}
\begin{algorithmic}
\STATE save display flags and OP scratch registers
\FOR{each visible token or template action}
  \STATE classify the token into a layout class
  \STATE load the class handler record from \texttt{39:5E45}
  \STATE read row count, row actions, and row cell counts
  \IF{the selected cell is an operand slot}
    \STATE recurse through the argument walker
  \ELSIF{the selected cell is a descriptor-backed template cell}
    \STATE map descriptor row/column to pixel coordinates
    \STATE emit the descriptor cell or marker action
  \ELSIF{the selected cell is a structural glyph}
    \STATE map it through the direct glyph path and emit the fixed glyph
  \ELSE
    \STATE convert it through the string or display-byte path
  \ENDIF
  \STATE update row, column, and overflow state
\ENDFOR
\STATE restore display flags and OP scratch registers
\end{algorithmic}
\end{algorithm}
```

## Evidence anchors

The page is intentionally an architecture summary, not a verifier log. These are the main
anchors for readers who want to check the disassembly. [confirmed]

| Address | Meaning |
|---------|---------|
| `39:4A74` | Main token/action dispatcher. |
| `39:4C27` | Class table lookup through `39:5E45`. |
| `39:4DCA` | Row-cell pointer computation for handler records. |
| `39:4DE6` | Row cell stream emitter. |
| `39:4E8E` | Generic two-byte cell emitter. |
| `39:4F1A` | Direct large-glyph classifier. |
| `39:4F08` | Text-column overflow check before marker handling. |
| `39:4E0A` | Argument-index marker emitter used by the row compositor. |
| `39:5167` | Multi-argument operand walker and tall-template row compositor. |
| `39:5949` | Row-step classifier for one-row versus two-row argument advance. |
| `39:5B10` / `39:5B1D` | Saved-E7 wrappers for ascending and descending alphabetic VAT searches. |
| `39:59E0` / `39:59F9` | `_FindAlphaUp` and `_FindAlphaDn` dispatchers. |
| `39:672E` | Template handoff for incoming `0x3D`. |
| `39:683D` | Descriptor cell-to-pixel mapper. |
| `39:68AE` | Geometry action handler. |
| `39:69C8` | Descriptor/fraction geometry selector. |
| `39:6ABF` / `39:6B1C` | Fraction focus rectangle and endpoint helper. |
| `39:6B66` | Generic string selector. |
| `39:66E9` / `39:66FE` | Reverse and forward argument-overflow cues. |
| `39:6712` | Overflow marker path; resets `curCol` and emits `:`. |
| `07:44DE` | Display-byte remapper. |
| `07:4588` | Large-font fixed glyph blitter. |
| `01:6293` | `_VPutMap` small-font pixel output. |

## MathPrint pipeline coverage

`tools/analyze_mathprint_saturation.py` bounds the coverage claim to nine
declared components: settled construction, settled rendering, metrics and
geometry, record allocation, editor layout, small-font/LCD output, point and
line primitives, large-glyph output, and alphabetic VAT selection. It
recursively follows direct ROM edges from named entries, seeds decoded table
destinations, overlays exact next-PC outcomes from 231 reset-origin traces, and
lists direct external targets. Computed dispatch destinations are manually
seeded; bcall and RAM bjump bodies remain outside the direct-edge walk. Of those
traces, 230 reach their state through calculator input. One explicitly
classified synthetic trace inserts an `EF36h` editor buffer through direct RAM
writes. The report keeps the two provenance classes separate.
`tools/mathprint-saturation.json` records the resulting branches and trace
hashes. [confirmed]

The analyzer can restore trace identities, provenance, and per-trace summaries
from a prior report and the digest-keyed cache. Regeneration therefore scans a
new trace once without reopening the other retained TLMT files. [confirmed]

None of the 231 report traces executes `39:5167`, `39:523B`, the saved-operand
wrappers at `39:5B10`–`39:5B38`, or the dispatchers at `39:59E0`/`39:59F9`.
The 231-digest trace cache also has no hit at those entries. [confirmed]
`_FindAlphaUp` at `07:50B5` executes once in 112 report traces, but every call
comes from the type-`16h` cleanup loop at `07:5544`. Each observed call returns
carry with OP1 unchanged; no trace supplies a successful alphabetic-search or
MathPrint caller witness. [confirmed]

The report is a symbolic-execution aid rather than a whole-machine proof. It
decodes fixed table rows and partitions selected projected input domains. The
scan-kind dispatcher at `34:5678` partitions all 256 incoming `A` values into
seven terminal paths. The shared draw helper at `34:6143` partitions the
$256 \times 2 \times 65{,}536 = 33{,}554{,}432$ projected tuples over incoming
`A`, `(IY+44h).3`, and the word at `0x8520`. Its predicates reduce those tuples
to 14 branch-path classes and ten terminal actions. This count covers the
projected inputs, not every register and RAM state. The marker-tail callee at
`34:759C` reduces 16 abstract predicate valuations to five return classes.
Stream length, arbitrary RAM, and unmodeled indirect targets remain outside
these finite models. [confirmed]

The page-7 domains partition all 32 masked type classes, 192 declared type/key
form pairs, all 8,192 type/record-marker pairs, and all 288 abstract candidate
decisions. A fifth domain covers both terminal return states. The candidate
projection includes direction, type equality, filter result, the `FFh`
sentinel, source relation, and current-best relation. These domains cover the
translated branch predicates and minimize representatives for their outcomes.
They do not enumerate arbitrary VAT length, every possible eight-byte name, or
the two extension bytes in the 11-byte OP scratch registers. [confirmed]

The extended raised-token classifier at `34:580C` has a caller-scoped domain of
3,047 packed-token states. `34:5866` handles numeric bytes and `B0h` first, and
`34:5887` skips `EF1Eh`. The remaining ordinary bytes and 11 two-byte token
families reduce to 12 complete classifier paths. The `5Fh` and `EBh`
designators enter bounded eight- and five-byte name scans. The loop at
`34:583D` accepts digits `30h`–`39h` and letters `41h`–`5Bh`; a source boundary
or any other byte stops it. The analyzer enumerates every accepted digit/letter
prefix, stop class, and counter exit. These are finite byte-class projections,
not claims that every packed token or name occurs in a calculator-created
expression. [confirmed]

Schema 2 of the report retains one deterministic representative for every
complete path-equivalence class in 25 finite models. It also computes an
exact minimum representative set for the branch outcomes in each model. The
minimums are per domain: the five- and eight-byte name-loop ABIs share branch
addresses, but a representative for one ABI does not cover the other. [confirmed]

| Finite model | Projected inputs | Path classes | Branch outcomes | Minimum representatives |
|--------------|-----------------:|-------------:|----------------:|------------------------:|
| Structural scan-kind dispatch | 256 | 7 | 12 | 7 |
| Structural-depth gate | 256 | 2 | 2 | 2 |
| Structural-insertion dispatch | 65,536 | 6 | 10 | 6 |
| Raised extended-token classifier | 3,047 | 12 | 22 | 10 |
| Five-byte raised-name loop | 493,112,577 | 125 | 10 | 4 |
| Eight-byte raised-name loop | 24,977,631,672,321 | 1,021 | 10 | 4 |
| Shared marker draw helper | 33,554,432 | 14 | 26 | 13 |
| Metric marker-tail gate | 16 | 5 | 8 | 5 |
| Editor action `0x03` controller | 131,072 | 11 | 9 | 4 |
| Editor action `0x04` controller | 131,072 | 5 | 5 | 3 |
| Reverse argument-overflow cue | 65,536 | 2 | 2 | 2 |
| Editor horizontal viewport | 17,179,869,184 | 8 | 6 | 2 |
| Editor vertical viewport | 17,179,869,184 | 8 | 6 | 2 |
| Editor vertical overflow cues | 4,294,901,760 | 5 | 8 | 3 |
| Editor left-overflow cue | 1,099,494,850,560 | 5 | 8 | 5 |
| Editor right-overflow cue | 281,474,976,710,656 | 5 | 10 | 4 |
| Glyph viewport gates | 30,064,771,072 | 3 | 4 | 3 |
| Embedded-record viewport gate | 4,294,967,296 | 2 | 2 | 2 |
| Record-allocation capacity | 36,893,488,147,419,103,232 | 6 | 6 | 2 |
| Saved-operand wrappers | 16 | 12 | 12 | 8 |
| FindAlpha type normalization | 32 | 31 | 8 | 4 |
| FindAlpha key preparation | 192 | 13 | 14 | 4 |
| FindAlpha record stepping | 8,192 | 8 | 12 | 4 |
| FindAlpha candidate reducer | 288 | 25 | 17 | 10 |
| FindAlpha endpoint | 2 | 2 | 4 | 2 |

The 25 models contain 1,343 path classes and 223 distinct modeled branch
outcomes. Their per-domain minimum corpora contain 115 representatives. Each
class records its concrete representative, projected-state count, terminal,
and complete branch-outcome sequence. These representatives saturate the
declared projections. They do not establish calculator reachability or cover
state outside those projections. [confirmed]

The table models also distinguish decoded rows from reachable indices.
`34:5935` scans 16 source-token rows but has 15 first-match classes: row 6
duplicates the `0006h` mapping at row 3 and can never win the first-match scan.
The report partitions the other 65,521 packed `D:E` values into the no-match
class. The render, allocator, and editor-class index models decode all 256
8-bit inputs. Types `0x1F`–`0x2B` select the 13 render and allocator rows;
class bytes `0x00`–`0x43` select the 68 editor rows. Other inputs read adjacent
ROM bytes. This records local index behavior without asserting that each
overread is reachable through a calculator entry. [confirmed]

The metadata rows use scan kinds `0`, `1`, `2`, `3`, `4`, and `6`. Natural
traces witness six of the seven dispatch classes. Scan kind `2` would take
`34:5680` into the fraction scanner at `34:56DF`, but no retained invocation
does so. Existing fraction construction instead reaches the same scanner
through another entry route. The outcome remains unresolved because the
metadata value proves local relevance but does not prove caller reachability.
[confirmed]

The report keeps complete path witnesses separate from individual branch
outcome witnesses. A class whose branch outcomes all occur somewhere in the
corpus is not necessarily a class traversed by one invocation. The editor ABI
at `34:6143` has seven complete live path witnesses. The render-table ABI has
one ROM-fixed class because `_LdHLind` fixes `A=0x43`. The `34:759C` model ends
at the callee return. It records the continuations at `34:755F`, `34:6FC9`, and
the tail-jump caller at `05:785F` separately. A branch outcome unique to each
return class identifies which callee paths have live witnesses. [confirmed]

| Component | Reachable instructions | Natural / all-evidence outcomes | Outcomes in CFG | Natural / all-evidence instruction coverage |
|-----------|-----------------------:|--------------------------------:|----------------:|--------------------------------------------:|
| Settled construction | 991 | 247 / 248 | 408 | 80.73% / 80.73% |
| Settled rendering | 1,898 | 255 / 257 | 302 | 97.47% / 97.47% |
| Metrics and geometry | 470 | 75 / 75 | 80 | 99.36% / 99.36% |
| Record allocator | 64 | 7 / 7 | 8 | 98.44% / 98.44% |
| Alphabetic VAT search | 236 | 17 / 17 | 92 | 34.32% / 34.32% |
| Editor layout | 2,776 | 255 / 255 | 1,098 | 33.03% / 33.03% |
| Small-font and LCD output | 413 | 81 / 81 | 122 | 75.54% / 75.54% |
| Point and line primitives | 508 | 50 / 50 | 134 | 59.65% / 59.65% |
| Large glyphs | 130 | 16 / 16 | 32 | 68.46% / 68.46% |

These counts describe the declared CFG and retained saturation corpus, not all
OS entry states. A branch with both outcomes observed is dynamically saturated
for that corpus. A branch with one or no outcomes remains open even when its
containing routine has been reached. Metrics and geometry and the allocator
have no wholly unobserved branch. The other seven components still do. Three of
the allocator's four branches and 35 of the 40 metric branches have both
outcomes. [confirmed]

The report classifies all 2,276 enumerated outcomes. Natural calculator input
exercises 1,005. The synthetic `EF36h` state adds three outcomes, for 1,008 across
all evidence. One allocator outcome is infeasible under its data invariant.
Two metric outcomes are infeasible under the calculator call ABI. The full
evidence set leaves 1,265 unresolved; the natural-only set leaves 1,268.
An unobserved outcome never becomes infeasible from absence alone. [confirmed]

The infeasible allocator outcome is the fallthrough at `33:4F4E`. The type
`0x2B` path loads rows and columns from record offsets `+0x13` and `+0x12`, then
`_HTimesL` (`00:1EF6`) computes their product. The matrix-creation path at
`02:5DCF` raises `_ErrDimension` when either dimension is zero. A valid settled
matrix record therefore reaches `33:4F4E` with a nonzero product and takes the
branch. [confirmed]

The calculator metric entries at `34:7377`, `34:737A`, and `34:7380` all pass
through `34:7386`, which loads `B=0`. The recursive route stores that zero at
`0x8512` and reloads it at `34:75F4` before `34:7606`. Induction over the
dispatcher recursion therefore fixes `B=0`. The `B!=0` outcomes at `34:73CD`
fallthrough and `34:765D` return are infeasible under this calculator ABI.
Synthetic direct calls to internal metric handlers do not share the ABI.
[confirmed]

The report computes two exact Z3 covers. The first preserves every individual
branch outcome observed in the supplied traces. It does not preserve complete
invocation paths, register or RAM states, dispatch indices, record cases, or LCD
write cases. The all-evidence and natural-only branch covers each select 22
traces. They preserve 1,008 and 1,005 outcomes in 3,987,022,530 and 4,081,707,150
bytes, respectively.

The tagged cover includes branch outcomes, complete observed paths, entry-state
projections, dispatch values, record types, LCD-oracle types, and every
independent oracle case. Its all-evidence universe has 1,313 tags and needs 169
traces. The natural-only universe has 1,310 tags and needs 168 traces. Every
independent oracle case creates an exclusive tag for at least one trace, so
this larger minimum is expected. Both covers minimize trace count first,
retained bytes second, and labels third. The broad set remains the RE and
regression corpus; the public gallery uses a smaller, diverse selection.
[confirmed]

The tagged cover preserves only states represented by its tags. It does not
turn unobserved RAM into an observed state or prove that the traces reach every
symbolic valuation. The separate exhaustive models state their preconditions;
the dynamic cover states what the retained traces actually exercise. [confirmed]

The 22-trace all-evidence branch cover retains the nested derivative, log-base,
integral, and **Y=**/table runs below. Other selected traces cover every outcome
in the radical run, so the exact solver omits it. The macro paths contain no
`memwrite` command or execution hook. The raw TLMT files remain outside the
repository; their hashes identify the exact inputs used by the report.
[confirmed]

| Input | Reproduction macro | Trace SHA-256 | Exclusive outcomes in the full branch cover |
|-------|--------------------|--------------|--------------------------|
| Nested derivative with tall body and value | `tools/macros/mathprint-nested-tall-nderiv.macro` | `e11c011b74df79165c55f7f64b699e3aa393bf8087f45ec89a73d616b73cdbb5` | 28 |
| Depth-four log-base and power tree | `tools/macros/mathprint-nested-depth4.macro` | `b8d970906e63db96d36847dfcafed91d97e73fc7699294cc8debd08e7affdd93` | 4 |
| Log-base marker insertion | `tools/macros/mathprint-logbase-boundary-insert.macro` | `a49e4c13c93358662713da7f5e07862f42863d60a70ce18e141a90987914008b` | 1 |
| Radical marker insertion | `tools/macros/mathprint-radical-nonspecial-insert.macro` | `e7b79e37149f2b9b4a986bdbb114a89b03cd452bbecc6da20490edc972895e98` | Omitted |
| Integral marker insertion | `tools/macros/mathprint-integral-boundary-insert.macro` | `328b8f52ebe939b35f79e676076984aa85ee59e05c06862647c4fc615069bb3c` | 2 |
| **Y=**/table/power round trip | `tools/macros/mathprint-yequ-table-power-insert.macro` | `ac719f540d2adfca05d2ffa415f065b83eaf407f04fca42f5ae63c440a746b9d` | 16 |

The retained `mathprint_integral_boundary_insert` trace reaches `34:6968`
taken, `34:6B6D` fallthrough, and `34:6B94` fallthrough through calculator
input. It supplies the natural witnesses recorded for all three outcomes.
[confirmed]

Four additional reset-origin traces close ten natural branch outcomes and four
complete editor-helper paths. Their macros use key input only. The screenshots
and `A` at each discriminator were checked before admission. [confirmed]

| Input | Reproduction macro | Trace SHA-256 | Complete `34:6143` path |
|-------|--------------------|--------------|-------------------------|
| Absolute-value marker | `tools/macros/mathprint-absolute-boundary-insert.macro` | `103f3acc7f1ad13d1bf88af45ecacdc7e34133e66cc9c00fb57587674357cacf` | `A=0x21` → display code `0x7C` |
| $e^x$ marker | `tools/macros/mathprint-e-power-boundary-insert.macro` | `c927963c5db9a1f6f18652213764eabbf7a4fa9f2d2a74b7dae320fe882d7917` | `A=0x25` → display code `0xDB` |
| $10^x$ marker | `tools/macros/mathprint-ten-power-boundary-insert.macro` | `eb337f479d112e88537f0950fd7d2a917d101cfafda98447fb717a9a35f1e1e4` | `A=0x26` → display code `0x1D` |
| Summation marker | `tools/macros/mathprint-summation-boundary-insert.macro` | `980b2d17df5753223881090235fcca4bb4e8457a37c6cb05eef8f7a54314adf8` | `A=0x29` → display code `0xC6` |

The synthetic `EF36h` trace uses
`tools/macros/mathprint-ef36-injected-buffer.macro`. Its two `memwrite`
commands place `EF 36 31 11` at the editor cursor. It is the sole synthetic
source in the 231-trace report. It supplies the only evidence for
`34:5A23` fallthrough, `34:6992` taken, and `34:6B94` taken. The full minimum
retains it; the natural minimum excludes it by construction. [confirmed]

The in-progress editor is a gap buffer. `editTop` (`0x96F4`) and `editCursor`
(`0x96F6`) bound the left segment. `editTail` (`0x96F8`) and `editBtm`
(`0x96FA`) bound the right segment. Moving across a structural object exposes
the six-byte right-segment marker `EF type id_lo id_hi EF 2D`. An insertion at
that boundary makes the metric walker enter `34:759C` with its parsed pointer
at `editTail + 6`. The comparison at `34:75A1` then returns Z, so `34:75A5`
falls through. [confirmed]

The live expression graph spans two record regions. `34:4ACE` starts at
the structural-record pointer in `0x8DAF` and stops at the entry pointer in
`0x8DBC`. `34:4AF0` advances by the structural record size. The child words
after each 20-byte header remain record IDs. `34:4A83` starts its leaf-record
walk at `0x8DBC`. It normally uses `0x8DBE` as the boundary. Bit 2 of
`(IY+1)` instead selects the extended boundary at `0x8DB1`. [confirmed]

`34:4AAF` handles the active gap during that leaf walk. When the gap bit is set
and the current record equals the pointer in `0x8DC2`, `34:4ABF` substitutes
`editBtm` as the next record pointer. Every other leaf advances by its 19-byte
prefix plus the payload length at `+0x11`. The active record's logical payload
is the concatenation of `editTop`–`editCursor` and `editTail`–`editBtm`.
This explains why a RAM dump can hold structural headers below the entry,
the active leaf in the gap, and later leaf records near the top of RAM.
[confirmed]

Four reset-origin RAM snapshots pin the cursor-to-record mapping. The compact
bytes and expected trees are in `tools/mathprint-editor-gap-oracles.json`.
Each reproduction uses key input only. [confirmed]

| Editor state | Active leaf | Logical gap payload | Cursor path | Sparse-state SHA-256 | Cursor-off LCD SHA-256 |
|--------------|-------------|---------------------|-------------|----------------------|-----------------------|
| Empty fraction numerator | `9` | cursor, `EF 1E` | numerator | `bcabb3961e1f37fe21b4e66c8bbfffb9a3812a162324e85273fdeed0beccc019` | `450e82a31ced68ed319a1c2e8d18d3e2d3813f097de8be9dc2a89d48289cc4c9` |
| Integral upper bound after `2` | `10` | `32`, cursor | upper bound | `1dab216a05a2604bdb51eaa8a347a881f4dcccb7c8f19965503d73812422f8d5` | `39b937b16e32e4e07f6ffc2d6e60842c0249fd51d3aa661b23af2d2cb8708cea` |
| Fraction denominator nested in an integral body | `15` | `32`, cursor | body → denominator | `7da6d7fdbb5ea848dda0afb1105237280a06b6dff994879df0a8c0b63e1a5f10` | `1297c2562d7c2fac9612aad6fc2e829ecb8f487606da6a079fb7d49d1c4c64d9` |
| Immediately after a completed integral | `7` | `EF 22 08 00 EF 2D`, cursor | root sequence after integral | `89dd708b40f3c77f2cb5392783256576be8f0014beea2b411b6ba860dd441ef4` | `80cc504e3a7c6c773906f1e64ca6916e48594fd0c66c946151b3bc9849647f64` |

The empty numerator keeps `EF 1E` in the right gap segment, while its sibling
denominator leaf resides near the high-memory boundary. The nested case links
integral body leaf `11` to fraction record `13`, whose second child is active
leaf `15`. The completed-integral case moves the active gap back to entry leaf
`7`; its cursor follows the complete six-byte type-`0x22` marker. These states
show that the graph itself preserves the editable nesting. [confirmed]

`decodeMathPrintEditorRam()` translates both record walks and the active-leaf
substitution. `decodeEditorExpressionGraph()` inserts a cursor at
`editCursor - editTop`, after checking the native token and six-byte marker
boundaries. It recovers the nested cursor path from record IDs and leaf bytes;
the screenshots do not participate in the decode. [confirmed]

`constructEditorExpressionProgram()` translates the inverse path. It allocates
the entry leaf at ID `7`, the transient type-`0x1F` wrapper at ID `6`, and the
same structural and child IDs as the captured arenas. The cursor contributes a
six-pixel cell at render depth zero and a five-pixel cell in a raised row. A
cursor immediately before `EF 1E` reuses that token's six-pixel empty-slot cell.
The ordinary structural metric formulas then propagate the active leaf's
height, width, and baseline through every ancestor. [confirmed]

The structural word at `+0x05` identifies the active one-based child along the
cursor path. A completed template outside that path retains its last child.
Containing leaves on the active structural path retain the descendant marker's
byte offset at `+0x0F`. The active gap also retains its pre-edit `+0x0F` and
`+0x11` words, so the cursor node carries those two state words explicitly.
They cannot be recovered from the concatenated gap payload alone. [confirmed]

For all four states above, decoding RAM to a cursor-annotated expression and
reconstructing it matches every record field by ID. Executing the reconstructed
record program in the cursor-off phase also matches the complete 96×64
calculator screenshot bitmap. The hashes in the last column cover all 768 LCD
bytes. [confirmed]

Ordinary token insertion follows `34:4775–47A4` into `34:4BB9–4C0D`. The
non-structural branch reaches the page-6 gap writer through `00:3699`.
`06:4341–4388` checks available space, stores the one- or two-byte packed token
at `editCursor`, and advances the pointer. In the captured root-leaf transition,
the write at `06:437A` stores `32h` at `9DE1h`; `06:437C` then changes
`editCursor` from `9DE1h` to `9DE2h`. [confirmed]

`tools/mathprint-editor-mutation-oracles.json` retains two adjacent pre/post
transitions. Appending `2` after root token `1` changes the active payload from
`31h` to `31h 32h`. Inserting `2` into an empty fraction numerator advances the
right gap boundary past `EF 1E`, so the token replaces the empty slot. The
second transition also shows that the type-`0x20` record keeps `EFh` at `+13h`
instead of recomputing that byte from the new `32h` numerator. The editor AST
therefore retains structural `+13h` state in addition to the active leaf's
`+0Fh` and `+11h` words. [confirmed]

`editorInsertPackedToken()` translates this mutation. For both transitions,
the mutated cursor tree equals the decoded post-key tree, reconstruction
matches every post-key record field, and execution matches the complete
cursor-off LCD bitmap. Structural template types other than the fraction,
structural deletion, and cursor navigation across structural boundaries remain
open.
[confirmed]

The blank entry line stores a zero-byte active leaf. Its only semantic node is
the cursor at byte offset zero; inactive empty leaves remain invalid. Selecting
the **n/d** template supplies source token `EF 2E`. `34:5935` maps that token to
type `0x20`. [confirmed]

The insertion follows `34:473A`, the depth gate at `35:7B37`, and the type
dispatcher at `34:5026`. The fraction case at `34:51B8–51D4` calls
`34:5467–547E`, which writes `EF 20 00 00 EF 2D` before the allocator patches
the structural record ID. In the reset-origin blank-root capture, the ROM
allocates fraction record `8`, numerator record `9`, and denominator record
`10`. It advances the structural depth from zero to one and selects numerator
record `9` as the active leaf. [confirmed]

`editorInsertStructuralTemplate()` consumes the decoded arena state because the
semantic cursor tree does not contain the next record ID or structural-depth
byte. For this capture, it produces `EF 20 08 00 EF 2D`, moves the cursor into
the empty numerator, and creates an `EF 1E` token in both children. The decoded
post-key tree, all five record headers, and the complete cursor-off LCD bitmap
match the calculator. [confirmed]

A second reset-origin transition begins with root payload `31` and a leaf-end
cursor. The same template path moves `31` into numerator record `9`, creates an
empty denominator in record `10`, and moves the cursor to the denominator. The
migrated numerator retains `word0F = 0` while `word11 = 1`; the editor AST keeps
that leaf-only state so reconstruction matches the ROM header. [confirmed]

A third transition begins with `12` and the cursor between the two tokens. It
moves the left segment, `31`, into numerator record `9`, creates an empty
denominator in record `10`, and retains the right segment, `32`, after the
six-byte fraction marker in the root leaf. The translated cursor tree, every
record field, and the complete 96×64 post-key LCD bitmap match the ROM capture
in all three transitions. [confirmed]

A fourth root transition begins with `12` and the cursor before both tokens. It
creates an empty fraction, selects numerator record `9`, and retains the entire
`31 32` right segment after marker `EF 20 08 00 EF 2D`. The children both hold
`EF 1E`; neither receives the right segment. Blank, leading, mid-leaf, and
leaf-end cases now cover every root cursor class. [confirmed]

A fifth reset-origin transition inserts a fraction after `1` in an outer
fraction's numerator. The outer fraction retains record `8` and child records
`9` and `10`; the allocator appends inner fraction `11` and child records `12`
and `13`. Parent leaf `9` changes from payload `31` to marker
`EF 20 0B 00 EF 2D`, migrated `31` becomes inner numerator `12`, and the cursor
moves to inner denominator `13`. Structural depth advances from one to two.
[confirmed]

This live allocation order differs from rebuilding the final expression from
an empty arena. The editor AST therefore retains structural and leaf record
IDs in addition to the semantic tree. The constructor honors those identities
while recomputing metrics and ancestor markers. For the nested transition, the
translated AST, every record field, and all 768 post-key LCD bytes match the
ROM capture. The additional transitions below cover the other numerator cursor
classes and the denominator child. [confirmed]

Inserting into the outer fraction's empty numerator consumes its `EF 1E`
placeholder. Parent leaf `9` becomes marker `EF 20 0B 00 EF 2D`; no empty-slot
token follows that marker. Inner fraction `11` receives empty children `12` and
`13`, and the cursor selects numerator `12`. The translated mutation matches
the complete record graph and post-key LCD bitmap. [confirmed]

With `12` in the outer numerator and the cursor between the tokens, insertion
migrates `31` into inner numerator `12` and retains `32` after the inner marker
in outer numerator leaf `9`. The cursor selects inner denominator `13`.
Reconstruction matches the seven-byte outer-numerator payload, all ancestor
metrics, and the complete LCD bitmap. [confirmed]

With the cursor before outer-numerator payload `31 32`, insertion retains both
bytes after marker `EF 20 0B 00 EF 2D`. The new numerator and denominator keep
their `EF 1E` placeholders, and the cursor selects inner numerator `12`.
Together with the blank, mid-leaf, and leaf-end transitions, this covers every
nested-numerator cursor class. [confirmed]

Moving the cursor to the outer denominator exercises child 2 of record `8`.
Insertion into its `EF 1E` placeholder replaces leaf `10` with the inner marker
and selects empty inner numerator `12`. Insertion after denominator token `31`
migrates that token into inner numerator `12` and selects inner denominator
`13`. The JavaScript reconstruction matches every record field and all 768 LCD
bytes in both states. [confirmed]

With the cursor before denominator payload `31 32`, insertion retains both
bytes after the inner marker and selects inner numerator `12`. With the cursor
between those bytes, insertion migrates `31` into inner numerator `12`, retains
`32` after the marker, and selects inner denominator `13`. These transitions
complete the blank, leading, mid-leaf, and leaf-end denominator classes. The
root leaf and both child leaves of one outer fraction now have natural-input
oracles for every cursor class. Deeper fraction positions remain open.
[confirmed]

Source tokens `B2h`, `BFh`, `C1h`, and `BCh` map to the one-child types
`0x21`, `0x25`, `0x26`, and `0x27` at `34:5935`. The dispatcher sends all four
through `34:5057`, `34:5473`, and `34:58A0` before allocation at `34:4862`.
The parent receives `EF type id_lo id_hi EF 2D`; the new child receives
`EF 1E`, and the cursor enters that child. [confirmed]

Four $e^x$ captures cover blank, leaf-end, leading, and mid-leaf insertion in
the root. Insertion at the end appends the marker. Leading and mid-leaf
insertion replace the packed token immediately to the cursor's right. Blank
absolute-value and $10^x$ captures exercise the other translated one-child
kinds. `editorInsertStructuralTemplate()` produces the decoded cursor AST,
every record field, and all 768 LCD bytes for all six transitions. [confirmed]

Source token `F1h` maps to nth-root type `0x24` at `34:594D`. The insertion
dispatcher takes `34:504F` into `34:51C0–51D9`. All four root cursor classes
continue through `34:51D6`, `34:5473`, the marker writer at `34:58A0`, and the
three-record allocator at `34:4862`. [confirmed]

Blank-root insertion places `Ans` (`72h`) in the index child and `EF 1E` in the
radicand child. The cursor enters the radicand. Leaf-end and mid-leaf insertion
move the payload left of the cursor into the index. Leading insertion creates
blank index and radicand children and enters the index. Leading and mid-leaf
insertion replace the packed token immediately to the cursor's right.
`tools/mathprint-editor-structural-mutation-oracles.json` captures the four
states. The translated AST, every record field, and all 768 LCD bytes match
their calculator states. [confirmed]

The radical template supplies source token `00BCh`; `34:5935` maps it to type
`0x27`. Insertion follows `34:473A`, the depth gate at `35:7B37`, and
`34:4169` into the type dispatcher at `34:5026`. The type-`0x27` path calls
`34:5037`, `34:5473–547B`, and the marker writer at `34:58A0–58B4` before
`34:4862–491D` allocates the structural record and its radicand leaf.
[confirmed]

Blank-root insertion allocates radical record `8` and radicand record `9`.
The parent leaf receives marker `EF 27 08 00 EF 2D`; child `9` receives
`EF 1E`, and the cursor selects that child. Leaf-end insertion retains the left
payload before the marker. With a token to the cursor's right, the ROM replaces
one packed token with the radical marker. It does not move left payload into
the radicand. The leading `12` capture therefore becomes radical → `2`, while
the mid-leaf capture becomes `1` → radical. [confirmed]

A fifth root capture begins with `3 L1` and places the cursor before the two-byte
`5D 00` token. Radical insertion removes both bytes and produces `3` → radical.
`editorInsertStructuralTemplate()` applies the same packed-token boundary rule.
[confirmed]

Insertion into either child of an outer fraction allocates radical record `11`
and radicand leaf `12`. Numerator insertion replaces payload in leaf `9`;
denominator insertion replaces payload in leaf `10`. The controller depth moves
from one to two, and the cursor selects leaf `12`. Blank, leaf-end, leading, and
mid-leaf captures cover all four cursor classes in both children. [confirmed]

The allocator loads the entry-record pointer from `0x8DBC` and invokes unnamed
bcall ID `53ADh` at `34:4900`–`34:4905`. Initialization at
`34:4908`–`34:4928` overwrites the new ID, type, parent, selector, and depth
fields. It skips bytes `+07h`–`+10h` and does not write `+12h` or `+13h`.
Structural insertion therefore retains the byte that occupied `+13h` in the
old entry record. Root insertion at a nonzero cursor offset retains the entry
leaf's first payload byte. Insertion at offset zero retains `EFh` because the
new marker becomes the first payload unit. A nested insertion does not derive
this byte from structural depth or from the active child. [confirmed]

Four additional captures begin with root token `3` and insert a second radical
into the first radical's radicand. Blank, leaf-end, leading, and mid-leaf cases
cover every cursor class in that child. The new radical record retains `33h`
from entry record `7`, including the blank case whose active radicand begins
with `EFh`. A blank fraction inserted at the same position also retains `33h`,
which exercises the shared structural-allocation rule. [confirmed]

`tools/mathprint-editor-structural-mutation-oracles.json` retains the five
macro and trace hashes, both RAM states, sparse arena bytes, screenshots, and
complete LCD hashes. [confirmed]

`editorInsertStructuralTemplate()` retains the old entry byte before
reconstructing the arena. Across all 17 radical transitions, its cursor AST
matches the decoded post-key tree, reconstruction matches every record field,
and execution matches all 768 LCD bytes. The fraction discriminator has the
same record and LCD parity. Radical and fraction insertion at other deeper
structural positions, remaining structural template types, structural
deletion, and structural-boundary navigation remain open. [confirmed]

Ordinary in-leaf navigation uses the page-6 gap movers. LEFT reaches
`06:4294–42C7` through `34:42B4` and `00:3B49`; RIGHT reaches
`06:42C8–4301` through `34:4193` and `00:367B`. Both paths call
`00:1FE7` so a two-byte native token crosses the gap as one unit. Structural
record markers remain on separate page-34 paths. [confirmed]

`tools/mathprint-editor-navigation-oracles.json` captures `12` with the cursor
at the end, after LEFT places it between the digits, and after RIGHT returns it
to the end. The middle state splits the logical payload into left byte `31h`
and right byte `32h`; its cursor offset is one. Its active leaf width is 12
pixels, not 18: before existing payload the cursor overlays the following cell
without adding width. At the leaf end, the cursor allocates a six-pixel cell
and the width returns to 18. All three reconstructed record sets and complete
cursor-off LCD bitmaps match their calculator states. [confirmed]

`editorMovePackedTokenCursor()` translates both directions and rejects a
structural boundary rather than applying the ordinary token rule there. The
same regression also closes an AST-decoder bug: after emitting a cursor inside
a numeric run, the following digit must begin a new atom before the two sides
are recombined around the cursor. [confirmed]

**DEL** removes the packed token at the right edge of the gap through
`34:4570`, `00:3687`, and `06:4393–43A4`. `06:43A5` reads the token and calls
`00:1FE7`; `06:439C` advances `editTail` once for a one-byte token and twice
when the classifier returns carry. Deleting `2` from the middle of root `12`
therefore advances `editTail` from `0xFC44` to `0xFC45` without changing the
cursor offset. [confirmed]

An empty active leaf takes the additional `34:4549–455B` path. It inserts
`EF 1E` through `34:4BB9–4C0D` and the page-6 gap writer, then calls the LEFT
mover so both bytes land in the right gap segment. The cursor remains at byte
offset zero before the restored square. [confirmed]

`tools/mathprint-editor-deletion-oracles.json` retains adjacent root and
fraction-numerator deletion states. `editorDeletePackedToken()` produces both
decoded post-key trees exactly, reconstruction matches every record field, and
execution matches both complete cursor-off LCD bitmaps. The finite tests also
delete a two-byte native token as one unit. Deleting an embedded structural
record remains open. [confirmed]

`34:789A` first distinguishes the table-equation context from other editors.
On its fallthrough, `34:75AB` reads the marker type from `editTail + 1`.
`34:40F9` groups fraction (`0x20`), nth-root (`0x24`), and power (`0x2A`)
markers; `34:75B0` takes its Z branch for this set. `34:75B8` then reads the
nesting counter at `0x8515`, and `34:75BB` distinguishes zero from nonzero
depth. `tools/macros/mathprint-power-boundary-insert.macro` reproduces the
top-level power-marker path. The **Y=**/table/power round trip above reaches this
gate after returning to **Y=**, but the conjunction tested by `34:789A` is false
at that invocation. It therefore witnesses `34:75A9` fallthrough, not taken. The
table-equation outcome at `34:75A9` taken, the non-special marker outcome at
`34:75B0` fallthrough, and the nested special-marker outcome at `34:75BB`
fallthrough remain unresolved under natural input. Injected-state probes prove
that each local path is feasible, but they do not prove calculator
reachability. Those three `34:759C` injected-state probes are absent from both
minimized corpora. [confirmed]

The record-oracle corpus contains 114 captured cases and includes every type
from `0x1F` through `0x2B`. Types `0x20`–`0x2B` have decoded record nodes and
complete accepted-write oracles. The type-`0x1F` case is the transparent
one-child wrapper described below: it has a captured node, child write stream,
and pixel-exact entry screenshot, but it emits no primitive of its own. This
saturates the 13-type record-node domain, not the internal branches of every
handler. [confirmed]

`34:6143` has two distinct entry ABIs. Render-table row 0 at `34:6119` contains
the bytes `43 61`, the pointer `6143h`. `_LdHLind` at `00:0033` executes
`LD A,(HL); INC HL; LD H,(HL); LD L,A; RET`. Its low-byte load therefore makes
a type-`0x1F` table dispatch enter `34:6143` with `A=0x43`. That value follows
the fixed default path to the seven-row bitmap at `34:61BE`; `(IY+44h).3` and
`0x8520` do not affect this ABI. [confirmed]

The editor calls the same helper through a different route. `06:7F29` loads
`editTail`, `06:7F2D` reads the marker type at `editTail + 1` into `A`, and
`06:7F2E` calls the bjump descriptor at `ram:30BD`. Its bytes
`CD 09 2B 43 61 74` select `34:6143`. The radical-marker trace enters with
`A=0x27` and `(IY+44h).3` set, selecting the bitmap at `34:630C`. The integral
trace enters with `A=0x22` and emits display code `0x7C`. The reproductions in
the coverage table use
`tools/macros/mathprint-radical-nonspecial-insert.macro` and
`tools/macros/mathprint-integral-boundary-insert.macro`. Absolute value,
$e^x$, $10^x$, log base, and summation add live paths for `A=0x21`, `0x25`,
`0x26`, `0x28`, and `0x29`. The editor marker domain also includes the
exceptional `0x2C` marker produced by the `EF36h` synthetic state. The default
bitmap path handles it. [confirmed]

`34:4FD9` allocates type `0x1F` as a transient one-child root record.
`34:6028` loads `A=0x1F`, and `34:602B` calls `34:7844` to store the current
render type at `0x8DE7`. The following jump to `34:636C` renders child 1 without
using the table at `34:6119`. A natural matrix-entry capture contains wrapper
ID `6` at `0x9DB7` and child leaf ID `7` at `0x9DF9`. Executing the captured
graph through the JavaScript walker reproduces its 76-by-10-pixel entry image
with zero differences. The wrapper contributes no pixel operation; all 175
accepted writes come from its child program. [confirmed]

The JavaScript record walker therefore keeps the two ROM-proven ABIs separate.
A one-child type-`0x1F` node follows the natural `34:636C` continuation. A
childless node models the independent `34:6119` table entry and its row-0
bitmap. No retained natural trace combines `0x8DE7=0x1F` with `34:6105` →
`34:6143`, so the latter remains a decoded table ABI without a natural record
dispatch. [confirmed]

Page `39` layout control remains incomplete. Its class and handler tables, argument
order, row composition, descriptor mapping, and draw paths are decoded. The
browser-side ROM engine now translates the `39:4A74` token/action dispatch and
its `IY+2` exponent-context and `IY+9` fraction-context class adjustments
through `editorTokenDispatch()`. It returns the measured-template handoff at
`39:672E` separately from normal `39:4C27` handler lookup. [confirmed]
The `editorArgumentClamp()`, `editorRowFromArg()`, and
`editorLayoutArgument()` translations cover the arithmetic at `39:50CF`,
`39:5101`, and `39:513E`: argument-count clamping, six-row window origin,
seven-row mapping, and restoration of the caller's baseline row. The
cross-page continuation after `39:50CF` remains caller state. [confirmed]
The `editorSubexpressionWindow()` and `editorSubexpressionCell()` helpers
translate `39:4C5A` and `39:4CA4`: they compute the visible slot, select the
`984A` or caller-supplied cell base, and retain styled-argument and empty-menu
cross-page exits as explicit states. [confirmed]
`editorAdvanceArgument()` and `editorRetreatArgument()` translate the forward
and reverse slot branches at `39:5167` and `39:523B`. They distinguish list
endpoints, one- and two-row movement, subexpression fallback, both styled
scroll directions, and the saved-F2 search's carry exit. The forward two-row
path compares `0x844B` with 6 at `39:5181`; the reverse path compares it with 3
at `39:5244`. These jumps reach `39:4C5A` before the styled-record test. Calls
into scroll helpers remain explicit effects. The saved-operand wrappers derive
their alphabetic outcomes from one shared VAT state. A missing VAT state
stops at the saved-F2 search instead of selecting a scroll branch.
The increment-wrap guard cannot execute: its preceding unsigned predicate
requires a nonzero count and an index at most `count - 2`. [confirmed]

The saved-operand wrappers at `39:5B10`–`39:5B44` move nine-byte operand
buffers through OP1 at `0x8478`. The E7 wrappers restore from `0x85E7`; the F2
wrappers restore from `0x85F2`. Each restore uses `_Mov9B` at `00:1A92`.
The ascending wrappers then call `39:59E0`; the descending wrappers call
`39:59F9`. Bit 5 of `(IY+11h)` gates the entire wrapper. A clear bit preserves
the incoming carry and performs no copy or search. With the bit set, search
carry returns without writeback. Carry clear copies OP1 back to the selected
source: `39:5AD2` writes `0x85E7`, and `39:5B08` writes `0x85F2`. The page-7
search receives the restored OP1 and the current VAT state. The styled overflow
path applies the F2 writeback before it restores and searches E7. A raw-byte
interpreter covers all 4,096 wrapper, gate, derived-carry, and buffer-source
combinations. It also covers every value in every restored byte and every
value in the seven selected payload bytes written back to a saved operand.
[confirmed]

These page-39 buffers contain the nine identity bytes copied by `_Mov9B`.
The page-7 routine uses the complete 11-byte OP scratch registers through
`00:1A0F`, `00:1AE7`, and `00:1A4E`; `07:522E` also writes OP2+9 at `0x848C`.
The translation models the nine identity bytes used for selection and saved
operand writeback. It does not claim parity for the two extension bytes in the
page-7 scratch registers. [confirmed]

The local dispatcher below those wrappers is translated separately by
`editorAlphaSearch()`. `39:59E0` and `39:59F9` first call `39:5A17`, which
tests whether `0x85DE` is class `0x02`. The ascending class-2 path enters
`39:59AF`, emits `0Dh` through `RST 28h`, and seeds OP1 with `14h` at
`39:59C6`. The descending path enters `39:59B6`, scans the eight payload bytes
at `0x85E7+1` through `39:5A2E`, emits `0Ch`, and conditionally calls
`39:1BAF` when the emitter leaves carry set before the same `14h` seed.
[confirmed]

For other classes the ascending and descending paths execute `XOR A`, then
cross to `00:3A53` and `00:306F`, respectively. The fixed-bank stubs reach
`07:50B5` (`_FindAlphaUp = 4A44h`) and `07:50B8`
(`_FindAlphaDn = 4A47h`). Both bcalls take the current variable name in OP1.
They return the selected variable in OP1 and OP3 and its VAT pointer in `HL`;
carry reports that no matching entry remains. Carry clear then calls
`39:5C2E`; only class `0x03` with subclass byte `0x01` enters `39:1942`.
`A=06` repeats the alphabetic search, while every other value returns with
carry clear. The JavaScript model derives each result from OP1 and a logical
VAT snapshot. It derives the post-search `A` from the selected OP1 type, so a
protected-program entry repeats without an injected return sequence. Nested
and multi-argument states can therefore exercise the search without replaying
an LCD stream. [confirmed] for the page-39 control flow and bcall identities;
[confirmed] for the page-7 input, output, and flag behavior.

`editorFindAlphaVat()` translates the selection state over an explicit logical
VAT snapshot. Each snapshot entry contains its nine-byte OP-format identity,
VAT type-byte address, and data-page byte. `07:50BB` loads `A=00h`, discarding the caller's
value; `07:5104`–`07:511D` always compare the normalized type class.
[confirmed] `07:5247` maps protected programs to the program
class, complex lists to the list class, type `0x0B` to equation class `0x03`,
and types `0x18`/`0x19` to class zero. [confirmed] The comparator at
`07:5199` subtracts eight name bytes from OPx+8 down to OPx+1. Borrow
propagation makes OPx+1 the most-significant alphabetic byte. The scan retains
the nearest name above or below the incoming OP1, independent of physical VAT
entry order. It returns the selected identity in OP1 and OP3, its VAT pointer
in `HL`, and carry at an alphabetic endpoint. [confirmed]

The decoder at `07:51BE` rejects a first name byte below `41h` or equal to
`72h`. It also handles list prefixes `3Ah` and `5Dh 40h` through
`MenuCurrent`, `inGroup`, and bit 0 of `(IY+0)`. While `inGroup` is set, an
archived candidate uses its page byte for the final `41h`/`72h` gate.
`OP1+2=FFh` is the ascending-start sentinel at `07:5151`; it admits every
filtered Up candidate and makes Dn return carry. [confirmed]

Before comparison, `07:50C4`–`07:50F7` chooses the VAT region and clears unused
key bytes. Program-like named types, names beginning with `5Dh`, and List/CList
keys beginning with `FFh` use the named region. Other List/CList forms,
including `72h` and `3Ah`, use the fixed-token region. The fixed path preserves
three name bytes and clears the remaining five. The named path clears bytes
after the NUL-terminated name length; the one-byte `5Dh` prefix has comparison
length two. A failed search restores the original, unpadded identity from OP3.
[confirmed]

Success returns `A=00h`, Z set, and carry clear. Failure restores the incoming
identity to OP1/OP3 and returns `A=FEh`, Z clear, and carry set. [confirmed]

`editorDecodeAlphaVatSnapshot()` builds the logical snapshot from a 64 KiB RAM
image. The initializer at `07:50BE`–`07:50F9` chooses one of two regions.
Named/list-name searches start at `progPtr` and stop at `pTemp`; fixed-token
searches start at `symTable` and stop at `progPtr`. [confirmed]

For a type cursor `H`, both entry forms store T2 at `H-1`, version at `H-2`,
data address low/high at `H-3`/`H-4`, and page at `H-5`. A fixed entry stores
three name bytes at `H-6`–`H-8` and advances to `H-9`. A named entry stores its
length at `H-6`, name bytes downward from `H-7`, and advances by `7+length`.
The `72h` and `3Ah` forms use the fixed three-byte step. Type `09h` decodes a
fixed comparison key but uses the variable-length step at `07:512C`–`07:5149`.
[confirmed]

`editorForwardOverflowCue()` and `editorReverseOverflowCue()` translate the
closed cue routines at `39:66FE` and `39:66E9`. The reverse routine subtracts
the selected argument at `0x85E0` from the count at `0x85E2` with byte
arithmetic. A result below 8 returns without drawing. Other results place
display code `0x1F` at column 1 and row `(winBtm - 1) & 0xFF`. The forward
routine places `0x1E` at row 1, column 1. Both routines restore the word at
`0x844B` after their display call; the reverse early return leaves it untouched.
A raw-byte interpreter exhausts all 65,536 count/index pairs and every
`winBtm` byte. [confirmed]
`editorFirstArgumentAction()` and `editorAdvanceAction()` compose those
walkers with actions `0x03` and `0x04`. They preserve the zero-count
256-iteration loop, byte-wrapped first-slot arithmetic, the one-call
action-`0x04` branch, and the flag-controlled tails. The tests exhaust all
65,536 count/index byte pairs for both values of bit 0 in each outer
controller. The walker tests separately exhaust its layout-class and row
predicates. [confirmed]
The retained corpus observes 255 of 1,098 declared editor branch outcomes. It
does not translate every key-to-graph mutation, cursor action, menu, error, or
row-composition path. The live RAM decoder covers a complete captured graph;
it does not predict the next graph from an arbitrary key action. [confirmed]

Accepted LCD-write parity is a separate result. The translated cases compare
every synchronous accepted data write, including writes that leave the byte
unchanged. Timer-interrupt run-indicator writes stay outside the MathPrint
parity surface. A matching byte stream proves the tested construction and draw
path; it does not close an unobserved editor or parser branch. [confirmed]

## Filled and nested-integrand traces

Two reset-origin TLMT v2 traces use the pinned ROM SHA-256
`7d9a7d96d89fc552ebee6afdbdd011fdc6047be9c16d308245dff07eb1f7bd6d`.
The raw traces remain outside the repository because they are 162 MB and 202 MB.
`tools/mathprint-trace-report.json` records their hashes, emulator provenance,
exact entry counts, state bytes, and replay results. [confirmed]

`web/mathprint/draw-order.json` preserves the visible pixel mutations after the
final expression key press. The filled-integral trace contains 351 accepted LCD
writes that change 522 pixels; the nested trace contains 391 writes that change
610 pixels. This sequence includes both set and clear transitions, so the
interactive preview can replay the controller's write order instead of an
inferred glyph order. [confirmed]

| Scenario | Page `0x39` editing hits | Final state | Settled LCD replay |
|----------|--------------------------|-------------|--------------------|
| `int(1,2,X^2,X)` | `4CA4` ×1, `4DCA` ×2, `4DE6` ×1, `4E8E` ×7, `4F1A` ×14 | `0x85E1=04`, `0x85E8=00` | 43×20; zero pixels differ from the model. |
| `int(1,2,(1//2)X,X)` | The same handler entries, plus `683D` ×5, `68AE` ×1, and `69C8` ×1 | `0x85E8=10`, `0x85EB=06`, `0x85EE=02`, `0x85EF=02` | 47×23; zero pixels differ from the model. |

Both traces execute `eqdisp_emit_subexpr2` at `39:4CA4`, not the static
multi-argument entry at `39:5167`. The nested case also executes the descriptor
cell mapper and geometry selector, confirming that handler-record emission and
descriptor geometry compose in one rendered expression. Neither trace reaches
the exact entries `39:5167`, `39:5949`, `39:5B10`, `39:5B1D`, or `39:6ABF`.
[confirmed]

The settled walker dispatches object kinds `0`–`12` through the word table at
`34:7012`. The handlers are `34:6D0C`, `706A`, `70B8`, `702C`, `7133`, `70A0`,
`70E2`, `70E2`, `7087`, `7102`, `717E`, `70C1`, and `71C6`, in order. Kinds 6
and 7 share `34:70E2`. The nested trace also visits transient records near
`0xFBDB` and `0xFBEF`, so the final RAM dump does not contain every walked
record. [confirmed]

These page `39` entries occur before the final **GRAPHVAR** key press. The
settled redraw after that key does not re-enter them. It calls `34:6D26` and
`34:737A` from `34:4347` and `34:434A`, then traverses the display objects from
`34:6016`. [confirmed]

For the nested scenario, `tools/analyze_mathprint_draw_trace.py` attributes all
391 visible-changing writes after the final key. The nearest page `34` frames
are `34:5FE7` → `ram:34E9` (158 writes), `34:6CA8` → `ram:3CE1` (96),
`34:5DA2` → `ram:3573` (78), `34:5EA3` → `ram:3567` (24), and `34:5DBA` →
`ram:3579` (10). The remaining 25 writes precede the page `34` object traversal
and come from the large-font path. The fixed-page stubs dispatch to page `04`
line and point routines and page `01:6297` small-font output. [confirmed]

The point wrapper at `34:5E85` clips each object coordinate through `34:5DD1`
and `34:5DEF`. Its closed tail at `34:5E98`–`34:5EA6` passes `B=x`,
`C=63-y`, and `D=1` to `_PointOn` at `04:4155`. Dynamic samples include
`(x,y)=(3,0)` → `BC=033Fh` and `(32,20)` → `BC=202Bh`. [confirmed]

The line wrappers share the viewport state at `0x8DFA`–`0x8E04`. The byte at
`ram:8DFA` is the physical screen $x$ origin, while the word at `ram:8DFE` is
the logical record $x$ origin. `ram:8DFB` and `ram:8E00` are the corresponding
physical and logical $y$ origins. Keeping those pairs separate matters in
shifted editor modes even though all four values are zero on the normal home
entry line. [confirmed]

`34:5D96` passes a clipped vertical segment to `04:431D`; `34:5DA6` swaps the
axes and passes a clipped horizontal segment to `04:4382`. The nested trace's
fraction rule enters `34:5DA6` with object coordinates `x=1`–`5`, `y=6` and
origins `x=16`, `y=5`. Page `04` receives endpoints `(17,52)` and `(21,52)`.
[confirmed]

The structural handlers retain coordinates and dimensions as 16-bit words.
For example, `34:62B4`–`34:62C3` reads a radical child's width word, increments
`DE` three times, and passes the resulting word endpoint to `34:5DA6`.
`34:620A`–`34:622C` performs the corresponding word comparison for a fraction.
The translated renderer therefore accepts widths beyond 255 and wraps additions
at 16 bits before viewport clipping. A radical with record width 258 reaches a
clipped vinculum from $x=-167$ through $x=87$ instead of rejecting the record
as byte-sized geometry. [confirmed]

Render-record type `0x22` dispatches through `34:6105` and the table at
`34:6119` to `34:622F`. The word at record offset `+7` is the integral-sign
height $h$. The handler draws the inclusive stem `(2,1)`–`(2,h-2)`, then hook
points `(3,0)`, `(4,1)`, `(1,h-1)`, and `(0,h-2)`, in that order. [confirmed]

Render-record type `0x20` dispatches to `34:620A`. The handler renders child
records 1 and 2 through `34:636C` and `34:6378`, then reads each child's word at
offset `+7`. It draws an inclusive horizontal line from `(1,y)` to
`(max(w_1,w_2)+1,y)`, where the parent word at offset `+0x0B` supplies $y$.
The nested-fraction trace reaches the line wrapper with `BC=1`, `DE=5`, and
`HL=6`, yielding `(1,6)`–`(5,6)`. [confirmed]

Render-record type `0x2A` dispatches to a `JP 34:636C` at `34:6375`.
`34:636C` selects child record 1 through `34:6CCD` before entering the recursive
renderer. The wrapper emits no point, line, or glyph itself. The corrected
record-table trace identifies `0x2A` as the `X^2` root type. [confirmed]

Render-record type `0x27` dispatches to the radical handler at `34:62A1`. It
emits the ten-byte root-hook bitmap through `34:62D0`, draws the vertical stem,
selects child 1, and reads that child's word at offset `+7`. It then draws the
inclusive vinculum from `(2,0)` through `(w+3,0)` and renders child 1 through
`34:660A`. The cursor-free history redraw for `sqrt(X^2+1)` has height 8 and a
child `+7` width of `0x17`. It reaches the wrappers with stem
`(2,1)`–`(2,7)` and vinculum `(2,0)`–`(0x1A,0)`. This produces the 26-pixel
rendered width. The final editable-entry redraw has child width `0x1D` and a
vinculum endpoint of `0x20`; cursor and edit-state geometry therefore remain
separate from history-echo geometry. [confirmed]

Render-record type `0x21` dispatches to the absolute-value handler at
`34:6347`. The parent words at `+7` and `+9` supply height and width. The
handler draws inclusive vertical bars at `x=2` and `x=w-4`, then renders child
1 through `34:636C`. The cursor-free `abs(X-3)` history redraw reaches the line
wrapper with `(x,y_1,y_2)=(2,0,6)` and `(0x1A,0,6)`. [confirmed]

Render-record type `0x24` dispatches to the nth-root handler at `34:6315`. It
renders index child 1, emits the root-hook bitmap at `x=w_1-1`, draws its short
vertical segment, renders radicand child 2, and draws the vinculum. The
cursor-free `nthroot(3,X+1)` history redraw reaches the wrappers with vertical
segment `(5,3)`–`(5,4)` and vinculum `(5,2)`–`(0x18,2)`. [confirmed]

The remaining settled render types map to calculator constructs through the
source-token table at `34:594D` and post-**ENTER** traces. Type `0x23` renders
`nDeriv(`, `0x25` renders $e^x$, `0x26` renders $10^x$, `0x28` renders
`logBASE(`, `0x29` renders summation, and `0x2B` renders a dimensioned matrix.
Type `0x1F` is a transient one-child root type. The main draw entry at
`34:6016` selects its child directly through `34:636C`, so an ordinary history
redraw does not dispatch that root through `34:6105`. [confirmed]

Types `0x25` and `0x26` share the body at `34:6381`. The handlers position and
conditionally emit fixed display codes `0xDB` and `0x1D`, respectively. They
then render child 1. The child record supplies its local origin through offsets
`+0x0B` and `+0x0D`. [confirmed]

Type `0x28` dispatches to `34:63B2`. It emits the three bytes returned by
`_KeyToString` for `00C1h`, renders child 1, emits the opening compound shape
through `34:5D1A`, renders child 2, and emits the closing compound shape through
`34:5D07`. The settled `logBASE(2,8)` root has child IDs `0x0010` and `0x0011`.
[confirmed]

Type `0x29` dispatches to `34:6504`. It conditionally emits display code
`0xC6`, renders children 1–3, and surrounds child 4 with the compound emitters
at `34:5D1A` and `34:5D07`. It also conditionally emits display code `0x3D`
between children 1 and 2. The settled `sum(N,1,3,N^2)` root contains child IDs
`0x0014`–`0x0017`. [confirmed]

Type `0x2B` dispatches to `34:65AA`. It emits the left vertical bracket and its
two inward points, renders the matrix elements in child-ID order, then emits
the right bracket and its points. `33:4F23` derives the element-loop bound from
the dimensions at record bytes `+0x12` and `+0x13`. The high byte at `+0x12`
stores the column count. Byte `+0x13` stores the row count. A settled
$2\times2$ identity matrix renders four children between the bracket operations.
[confirmed]

The type-`0x2B` constructor lays out elements in row-major order. For element
width $w_{r,c}$, height $h_{r,c}$, and baseline $b_{r,c}$, define each column
width, row baseline, descent, and height as [confirmed]

$$
\begin{aligned}
C_c &= \max_r w_{r,c}, \\\\
B_r &= \max_c b_{r,c}, \\\\
D_r &= \max_c(h_{r,c}-b_{r,c}), \\\\
R_r &= B_r+D_r.
\end{aligned}
$$

The first column begins at $x_0=6$, and each later column begins after the
previous extent and a six-pixel gap. The first row begins at $y_0=0$, and each
later row begins after the previous extent and a two-pixel gap:

$$
\begin{aligned}
x_{c+1} &= x_c+C_c+6, \\\\
y_{r+1} &= y_r+R_r+2.
\end{aligned}
$$

Each element is centered horizontally and baseline-aligned vertically:

$$
\begin{aligned}
X_{r,c}
  &= x_c+\left\lfloor\frac{C_c-w_{r,c}}{2}\right\rfloor, \\\\
Y_{r,c} &= y_r+B_r-b_{r,c}.
\end{aligned}
$$

For $m$ rows and $n$ columns, let $N_e$ be the element count, $H$ the matrix
height, $W$ the matrix width, and $y_c$ the vertical center:

$$
\begin{aligned}
N_e &= mn, \\\\
H &= \sum_r R_r+2(m-1), \\\\
W &= 12+\sum_c C_c+6(n-1), \\\\
y_c &= \left\lfloor\frac{H}{2}\right\rfloor.
\end{aligned}
$$

The constructor stores $N_e$, $H$, $W$, and $y_c$ in the words at `+5`, `+7`,
`+9`, and `+0x0B`, respectively. [confirmed]

Primitive matrix cells all have the same baseline, so they cannot distinguish
baseline alignment from height centering. A mixed-height $1\times2$ trace
does. Its first cell is `2//3^1`, with $(h,b)=(16,6)$; the second is
`(1+3)*abs(2)`, with $(h,b)=(7,3)$. The row has $(R,B)=(16,6)$, so the
calculator stores child origins `0` and `3`. Height centering would place the
second child at `5`, producing 116 wrong pixels while retaining the correct
79-by-16 dimensions. The baseline formula reproduces the captured graph and
all pixels exactly. [confirmed]

The word at `+0x11` stores the column count in its high byte and structural
depth in its low byte. The byte at `+0x13` stores the row count. When the matrix
contains more than one element, the allocation pass reserves the first child
leaf and then leaves one unused ID before scanning that leaf for nested
records. Primitive captures therefore have reachable child IDs `0x11`,
`0x13`, `0x14`, and so on when the matrix record is `0x10`. A structural first
cell uses `0x11` for the leaf, leaves `0x12` unused, and assigns its first nested
record ID `0x13`. [confirmed]

Five reset-origin traces cover primitive $1\times1$, $1\times2$, $2\times2$,
$2\times3$, and $3\times3$ matrices; a sixth covers the mixed-baseline case
above. The JavaScript constructor matches every captured record field, child
ID, and element position. The matrix result begins
at LCD row 9 and uses $x=95-W$, where $W$ is the outer leaf width at `+7`.
The generated streams match 32, 46, 92, 134, and 180 synchronous accepted LCD
data writes, respectively. [confirmed]

The $2\times3$ capture also contains eight accepted writes from the standard
timer's run-indicator handler at `01:6BBA`–`01:6BFA`. That handler reads and
rewrites LCD byte column 11 across rows 0–7 through `indicCounter` and
`indicBusy` at `0x8476`/`0x8477`. Removing those asynchronous writes leaves the
134-write MathPrint stream. The generated timeline models the synchronous
settled renderer and labels the interrupt writes separately in its oracle.
[confirmed]

`web/mathprint/rom-engine.js` implements the complete `0x1F`–`0x2B` structural
dispatch table as an executable record-graph walker. It resolves child IDs
through a node map, adds each child record's `+0x0B` and `+0x0D` origins on
recursive entry, preserves the handler's depth changes, and returns ordered
primitive and leaf operations. A settled expression enters this layer from a
type-`0x00` leaf program at `34:660A`. The program executor consumes its payload
in order and invokes embedded structural records against the same pen and depth
state. Row 0 uses the bitmap bytes at `34:61BE`, as fixed by the table-load ABI;
the captured type-`0x1F` wrapper instead uses the direct-child ABI above. The
`nDeriv(` handler renders child 1 again at `34:64B3`, then
places display code `0x3D` after that child's `+7` width. [confirmed]

The trace analyzer recovers leaf records from the resolver path. At `34:6CCD`,
`DE` is the one-based child index and `ram:8DF2` points at the parent. At
`34:6CD8`, `DE` contains the selected child ID and `HL` points at its resolved
record. Pairing these observations produces the complete record graph visited
by a settled render. [confirmed]

Leaf payload begins at record offset `+0x13`; the word at `+0x11` gives its
byte count. A one-byte scalar therefore stores its display byte at `+0x13`.
Compound leaf objects retain the subsequent bytes in the same record. A leaf
may construct and dispatch another structural record while it renders. The
analyzer preserves these secondary dispatches in instruction order. It uses the
first `34:660A` entry at the shallowest Z80 stack depth after the final key press
to identify the enclosing leaf program. [confirmed]

The analyzer also decodes the reachable settled graph into a semantic
expression tree. Structural child IDs recover argument order. A type-`0x2A`
record binds its exponent to the expression immediately before the
embedded-record marker. Balanced standalone `10h` and `11h` bytes become a
group node, so a postfix power after the close binds to the complete group.
The decoder advances over native two-byte tokens before interpreting grouping
bytes. The pair `5E10h`, for example, remains one token rather than opening a
group at its low byte. The decoder preserves `EF 1E` as an explicit extended
token. The renderer maps the pair to display code `0xF7`, so the decoded tree
exposes an unfilled template slot. The tree identifies the expression in a
trace without using LCD pixels or a screenshot. It describes the settled graph
consumed by `34:660A`. The browser-side ROM engine exposes the same decoder for
its generated AST view as `settledAst`. The live-editor wrapper applies this
decoder after `34:4AAF` substitutes the active gap payload, then inserts the
cursor at the byte boundary selected by `editCursor`. [confirmed]

A live matrix entry demonstrates why leaf decoding cannot treat every payload
as a flat token sequence. Before evaluation, wrapper ID `6` points to a leaf
whose payload begins `06 06 EF 27 08 00 EF 2D`: the outer and first-row
`06h` containers precede an embedded radical record. The next element contains
an embedded type-`0x2A` power marker. The decoder balances `06h`/`07h` matrix,
`08h`/`09h` list, and function/group delimiters, splits only on depth-zero
`2Bh` or row-closing `07h`, and resolves structural markers inside each cell.
It recovers `[[sqrt(2),X^2][3,4]]` as a 2-by-2 matrix AST from the captured RAM.
This raw-container representation is distinct from the evaluated type-`0x2B`
matrix record, although both decode to the same semantic matrix shape.
[confirmed]

Within that program, `EF type id_lo id_hi` invokes the structural record with
the given little-endian ID. `EF 2D` terminates or separates the embedded object
without drawing it. Ordinary payload bytes may follow. The settled
`sum(N,1,3,N^2)` entry invokes type `0x29`. Its body child emits `N`, invokes
type `0x2A`, and then closes the exponent object. This byte order matches the
structural dispatch and glyph trace order. [confirmed]

`executeSettledRecordProgram()` translates this byte stream rather than
replaying captured glyph events. Tests provide record headers, child IDs, and
payload bytes as input. They compare the generated display-code, coordinate,
depth, and order tuples with independently captured `34:6C37` observations for
absolute value, summation with an exponent, and nested `nDeriv(`. [confirmed]

The ordinary-token path resolves payload bytes through `smallfont_glyph_ptr`
at `01:6702`. A zero lead selects the word table at `01:4252`. The two-byte
leads `5Ch`, `5Dh`, `5Eh`, `60h`–`63h`, `7Eh`, `AAh`, `BBh`, and `EFh` select
tables at `01:4452`–`01:47E8`. The `5Eh` second byte selects one of four banks.
The `BBh` path clamps indices `F6h`–`FFh` to `F6h`. [confirmed]

Each selected pointer names one metadata byte followed by a counted
display-code string. Token `72h` therefore expands to `A`, `n`, `s`. Token
`C2h` expands to `s`, `i`, `n`, `(`. Two-byte token `5D 00` expands to `L` and
the subscript-1 display code. `_GetTokLen = 4591h` reads the count, and
`_Get_Tok_Strng = 4594h` copies the counted bytes. The browser uses the
ROM-extracted tables in `web/mathprint/token-strings.json`; it preserves native
token boundaries while constructing the settled record. [confirmed]

`34:6873` receives each resulting display code. It diverts parentheses `28h`
and `29h`, and braces `7Bh` and `7Dh`, to delimiter geometry. This includes
`28h` embedded in the spelling of `sin(`. `34:678C` dispatches parentheses to
`34:5D28` and `34:5D15`, and braces to `34:5E0F` and `34:5E14`. The four paths
emit points and lines instead of a large-font glyph bitmap. [confirmed]

Six reset-origin traces cover `Ans+1`, `Ans^2`, `sqrt(Ans)`, `X^Ans`,
`sin(X)`, and `sin(sqrt(X))`. Their generated graphs match every record field.
Their complete accepted-write streams contain 49, 40, 63, 32, 56, and 83
writes, respectively. Replaying each generated stream produces the same final
96×64 LCD bitmap as replaying its captured `34:660A` interval. `X^Ans` verifies
the variable-width small-font spelling. `sin(sqrt(X))` verifies a counted token
spelling before a structural child and the compound shapes around its taller
metrics. The structural record stores the containing leaf's accumulated
horizontal anchor at `+0x0D`. [confirmed]

Five reset-origin traces cover `L1`, `[A]`, `Y1`, `Str1`, and `X^L1`. Their
generated record graphs match every field after normalizing record IDs. Their
accepted-write streams contain 21, 35, 21, 42, and 22 writes. The generated
stream and captured outer-`34:660A` interval have the same byte-column, row,
and value for every write. Replaying either stream produces the same 96×64 LCD
bitmap. `X^L1` verifies two-byte spelling and width in the small-font exponent
path. [confirmed]

The translated renderer then maps the ordered operations through the ROM font
bitmaps, page-4 point and line behavior, `_VPutMap`, the page-7 large-glyph
path, and LCD byte packing. Six settled programs reproduce every accepted LCD
data write through the outer `34:660A` return: absolute value (49 writes), nth
root (69), radical (82), summation (66), `nDeriv(` (96), and a nested
integral/fraction (114). This comparison includes accepted writes whose value
does not change the displayed byte. [confirmed]

When a containing leaf appends a box with metrics $(h,b)$ to its current
metrics $(H,B)$, the metric pass unions the extents above and below the
baseline: [confirmed]

$$
\begin{aligned}
B_{\mathrm{out}} &= \max(B,b), \\\\
H_{\mathrm{out}} &= B_{\mathrm{out}} + \max(H-B,h-b).
\end{aligned}
$$

The reset-origin expression
`((1*A)/X)//(N-N)//(1*3)*((sum(X,2,1,N)*abs(3))/int(3,1,X,X))`
combines an outer fraction with $(h,b)=(21,6)$ and a summation with
$(h,b)=(19,9)$. Its live root record stores
$(H_{\mathrm{out}},B_{\mathrm{out}})=(24,9)$. Maximizing the
height and baseline independently would produce the incorrect height 21.

The small-font table at `03:4CD6` stores seven rows per glyph. `_VPutMap` emits
the five interior rows. It retains an interior zero row, but it does not emit
the padding row above or below the glyph. A row that crosses an LCD byte
boundary writes the right byte before the left byte at `01:63CE`–`01:641A`.
The large-font path emits all seven rows of its fixed cell. [confirmed]

The absolute-value constructor translates a closed slice of the earlier record
pass. `34:5935` maps source token `00B2h` through the table at `34:594D` to
render type `0x21`. The translated `34:4900`, `34:7393`, and `34:7609` paths
construct the containing leaf, the absolute-value record, its child leaf, and
their settled metrics. Fresh reset-origin traces for `abs(2)`, `abs(X/2)`, and
`abs(X+12)` match the generated record fields and every accepted LCD data write.
The trace streams are comparison oracles and are not constructor inputs.
[confirmed]

The compositional constructor translates the type-`0x2A` power and type-`0x27`
radical paths. `34:5935` maps source token `00BCh` through `34:594D` to render
type `0x27`; the containing leaf embeds the structural ID and constructs the
radicand as child 1. Its settled height, width, and baseline derive from the
child metrics. Raised radicals select the final five rows of the root-hook
bitmap at `34:62D0`, while outer radicals use all seven rows. [confirmed]

`34:5935` maps source token `00F0h` through `34:594D` to render type `0x2A`.
The containing leaf embeds `EF 2A id_lo id_hi EF 2D`, and child 1 contains the
raised payload. The metric branches at `34:7393` and `34:7609` distinguish the
first raised row from later raised rows. The JavaScript translation constructs
right-associated record trees and obtains raised-glyph widths from the ROM
small-font table. [confirmed]

Parentheses remain ordinary leaf tokens `0x10` and `0x11` in the settled
record. `34:6873` maps their display codes `0x28` and `0x29` to the compound
emitters at `34:5D1A` and `34:5D07`. A raised parenthesis keeps a six-pixel
token-cell metric. The shape height and baseline follow the enclosed payload.
The type-`0x2A` word at `+0x0D` stores the containing leaf width accumulated
before the power object. It is `0x1E` for `(X+1)^2`, after the five six-pixel
leaf tokens, and `0x0C` for the power inside `(X^2+1)`. [confirmed]

Five reset-origin traces cover `(X+1)`, `(X^2+1)`, `(X+1)^2`, `X^(1+2)`, and
`abs(X^2+1)`. The generated record graphs and complete accepted-write streams
match these traces. The streams contain 49, 60, 59, 32, and 60 writes,
respectively. [confirmed]

List braces remain leaf tokens `0x08` and `0x09`; `0x2B` separates elements.
Their display codes `0x7B` and `0x7D` enter the same matching-delimiter scans
at `34:689A` and `34:6951` as parentheses. The final renderer uses the brace
paths at `34:5E0F` and `34:5E14`. Each path emits two top points, an upper
vertical segment, a waist point, a lower vertical segment, and two bottom
points. The waist row equals the enclosed payload's baseline. It can differ
from the geometric midpoint. [confirmed]

Natural traces for `{1,2}` and `{sqrt(2),1}` pin the seven-row symmetric case
and the nine-row case whose baseline is row five. The translated native parser
retains element boundaries in a `list` node, including nested lists and
structural elements. Both oracle bitmaps match the calculator pixel for pixel.
Three seed-13 list-only differential cases add fractions, roots, variables, and
ordinary operators; all three match their natural calculator screenshots.
[confirmed]

When the immediate base of a power ends in a structural object, `34:70C1`–`7084`
merges that object's baseline and lower extent into the type-`0x2A` metrics.
It does not use the containing leaf's accumulated baseline: an earlier radical
to the left does not raise a later plain-token power. [confirmed]

After the leaf obtains its merged baseline, `34:77AD`–`77C1` revisits every
directly embedded structural record. It subtracts the record's baseline at
`+0x0B` from the leaf baseline in `ram:850A`, then writes the difference at
`+0x0F`: [confirmed]

$$
\mathtt{structure.word0F}
= \mathtt{leaf.word09} - \mathtt{structure.word0B}.
$$

For a trailing structural power base, the leaf baseline equals the power
baseline. The value is therefore `3` for `sqrt(X)^2` and `abs(X)^2`. A grouped
fraction base has baseline `6` and lower extent `7`; its outer power has
baseline `12`, height `19`, and therefore stores `6` at the fraction's
`+0x0F`. The fraction's visible numerator group requires two native
`10h`…`11h` pairs: the fraction scanner consumes the outer pair and retains
the inner pair in the numerator leaf. [confirmed]

For a grouped structural base, `34:70C1` saves the base baseline $b$ and lower
extent $d$. After `34:7283` returns the raised child's height $h_e$ in
`ram:8508`, the handler stores [confirmed]

$$
\begin{aligned}
b_p &= b + h_e - 2, \\
h_p &= b_p + d.
\end{aligned}
$$

The reset-origin trace for `(X^(X-2))^(N/X)^(N-3)` gives the inner base
$(h,b)=(10,6)$ and the outer power $(h_p,b_p)=(16,12)$. The inner type-`0x2A`
record stores `6` at `+0x0F`. The translated record fields and final LCD pixels
match the trace. The same rule at fraction depth gives inner $(h,b)=(8,5)$ and
outer $(h_p,b_p)=(14,11)$. [confirmed]

Reset-origin traces for `sqrt(X)^2`, `abs(X)^2`, and
`abs(sqrt(X^2+1))` match every generated record field and accepted LCD data
write. Their complete streams contain 35, 33, and 113 writes, respectively.
The nested case verifies the absolute-value bars, radical hook and vinculum,
powered radicand, and leaf glyphs in ROM emission order. [confirmed]

Fresh reset-origin traces for `X^2`, `X^12`, `2^X^2`, and `2^X^2^3` match the
constructed record fields and every accepted LCD data write. Their streams
contain 17, 22, 22, and 32 writes, respectively. These captures test one, two,
and three raised levels without supplying records or writes to the constructor.
[confirmed]

The type-`0x25` and type-`0x26` constructors map source tokens `00BFh` and
`00C1h` through `34:594D`. Both allocate one exponent child. The child begins at
`x=6`, uses raised small-font metrics, and determines the parent height, width,
and baseline. The handlers at `34:637E` and `34:63AD` emit fixed large-font
display codes `0xDB` and `0x1D` before rendering that child. The fixed symbol
stays in the large font when the containing expression is raised. [confirmed]

For exponent metrics $(h,w)$ and render depth $r$, the shared metric path at
`34:73DB` produces [confirmed]

$$
H=h+4,\qquad W=w+6,\qquad B=\max(h,6[r>0]).
$$

The six-row seed affects an exponential nested in a raised child. A
reset-origin `nDeriv(logBASE(1,2),X,e^2)` trace stores $(H,W,B)=(9,10,6)$ for
the type-`0x25` record. Its containing evaluation-value leaf stores height 9
and baseline 6, which places the value at row 4 in the type-`0x23` record.
[confirmed]

Reset-origin traces for `exp(12)`, `exp(X^2)`, `exp(1//2)`, and
`tenpow(X^2)` match every constructed record field and accepted LCD data write.
Each stream contains 22 writes. The JavaScript renderer generates the writes
from the expression tree, constructed records, structural handlers, ROM font
bitmaps, and LCD byte-packing logic. [confirmed]

The type-`0x28` constructor maps source token `EF34h` through `34:594D` and
reserves the base and argument leaves before scanning either payload.
`34:76A9`–`34:76BF` decrements the structural-depth byte through `34:79C9`.
It places the base one pixel below the argument baseline only when the remaining
depth is zero. The horizontal and height constants also select large-row or
raised-row geometry: [confirmed]

$$
\begin{aligned}
x_b &= 11+7[r=0], \\\\
y_b &= b_a + [d=1], \\\\
x_a &= w_b+17+7[r=0], \\\\
y_a &= 0,
\end{aligned}
$$

where $d$ is the one-based structural depth stored at `+0x11`, $r$ is the
render depth, and each bracketed comparison contributes one when true and zero
otherwise. The metric pass keeps the large-row base offset only at render depth
zero: [confirmed]

$$
\begin{aligned}
H &= \max(h_a, b_a+[r=0]+h_b), \\\\
B &= b_a, \\\\
W &= w_b+w_a+23+7[r=0].
\end{aligned}
$$

The type-`0x28` word at `+5` is an active-child selector, not a depth or metric
field. `34:4900`–`34:491D` initializes a new structural record to `1`.
`34:41BB`–`34:41D7` compares the selector with the type's child count and
increments it before entering the next child. Native-source construction follows
the `2,1` child order in the `34:59AC` row and leaves this field at `1`.
Interactive template entry can leave the same completed two-child record at
`2`. Neither value changes the type-`0x28` LCD handler. [confirmed]

Reset-origin traces for `logbase(12,345)`, `logbase(X,X^2)`,
`logbase(3,1//2)`, and `logbase(1//2,3)` match every constructed record field.
Their complete accepted-write streams contain 99, 79, 91, and 71 writes. These
cases cover multi-token children, a powered argument, and a stacked fraction in
each child position. [confirmed]

Reset-origin traces for `abs(logbase(A,3))`,
`abs(exp(2))-abs(logbase(A,3))`, and `abs(abs(logbase(A,3)))` cover structural
depths two and three plus mixed baselines in one leaf. The middle case stores
`2` at the second absolute-value record's `+0x0F`. The nested log-base records
place their base leaf at `y=3` while retaining height `9`; interactive template
entry leaves their active-child selector at `2`. After separating that editor
state from native-source construction, the stable graph fields and their 79-,
130-, and 95-write LCD streams match the traces. [confirmed]

Eight additional reset-origin traces cover radicals, sequences inside radicals,
nested radicals, powers inside radicals, and radicals inside powers. The deepest
cases are `sqrt(2^X^2)`, `sqrt(sqrt(2))`, `X^sqrt(2)`, and
`sqrt(X^sqrt(2))`. Their generated graphs and complete accepted-write streams
match the traces. The root bitmap comparison includes accepted writes whose
value does not change the LCD byte. [confirmed]

The type-`0x24` constructor maps source token `00F1h` through `34:594D`, then
allocates the containing leaf, structural record, index child, and radicand
child. The index uses the raised small-font metrics. The radicand begins four
pixels after the index width and four pixels below the parent origin. Its
height, width, and baseline determine the structural record metrics. At
`34:62D0`, an outer nth root selects all seven root-hook rows and a raised nth
root selects the final five. [confirmed]

Fresh traces for `nthroot(2,2)`, `nthroot(12,X+12)`,
`nthroot(3,X^2)`, and `X^nthroot(3,2)` match every generated record field and
accepted LCD data write. These cases cover a multi-token index, a structural
radicand, and a raised nth root. [confirmed]

The type-`0x20` constructor maps the stacked-fraction source token `EF2Eh`
through `34:594D`. It renders both children one depth below the containing leaf.
For numerator height $h_n$, denominator height $h_d$, and child widths $w_n$
and $w_d$, the settled metrics are [confirmed]

$$
\begin{aligned}
w &= \max(w_n,w_d), \\\\
x_n &= 2 + \left\lfloor\frac{w-w_n}{2}\right\rfloor, \\\\
x_d &= 2 + \left\lfloor\frac{w-w_d}{2}\right\rfloor.
\end{aligned}
$$

The vertical positions and parent metrics are:

$$
\begin{aligned}
y_d &= h_n + 3, \\\\
H &= h_n + h_d + 3, \\\\
W &= w + 4, \\\\
B &= h_n + 1.
\end{aligned}
$$

The numerator begins at $y=0$. The metric pass clears the numerator leaf's
word at `+0x0F`. The renderer consumes its payload through the word at `+0x11`.
[confirmed]

`34:4900` allocates structural records in a fraction numerator before it
allocates the enclosing type-`0x20` record. It allocates the numerator leaf
afterward. For `(X^2)//3`, IDs `0x11` and `0x12` identify the power record and
its exponent leaf. ID `0x13` identifies the fraction, `0x14` its numerator
leaf, and `0x15` its denominator leaf. The graph points from the numerator leaf
back to the earlier power record. A structural denominator follows the ordinary
recursive allocation order. A fraction nested in the numerator recursively
applies the same hoisting rule. [confirmed]

Thirteen reset-origin traces cover leaf, sequence, power, radical, nth-root,
and nested-fraction operands. The generated graphs match every captured record
field and ID. Their accepted LCD data-write streams also match through the outer
`34:660A` return. [confirmed]

Integral, summation, and `nDeriv(` records in a fraction numerator follow the
same hoisting rule. `34:4900` allocates the multi-argument record and reserves
its child leaves before it allocates the enclosing type-`0x20` fraction. The
nested structural record stores `0x10` at `+0x13`. Raised integral layout uses
a 10-pixel body-to-variable gap; the outer layout uses 12 pixels. In a raised
`nDeriv(X^2,X,...)` numerator, the body leaf stores `0x58` before the
type-`0x2A` marker, and the power record stores `4` at `+0x0D`. [confirmed]

Six reset-origin traces cover integral, summation, and `nDeriv(` numerators,
each with an ordinary body and a powered body. Before parity is accepted, the
trace analyzer must decode each settled graph to the asserted expression. The
JavaScript constructor then matches every record field and allocation ID, plus
every accepted LCD data write through the outer `34:660A` return. [confirmed]

The type-`0x22` constructor maps integral source token `0024h` through
`34:594D`. `34:4900` allocates the integral record, then reserves all four child
leaf IDs before it scans any child payload. The children hold the lower bound,
upper bound, body, and differential variable in that order. A structural child
allocates its records after all four reservations. A nested integral repeats the
same reservation rule recursively. [confirmed]

The bounds render one depth below the containing leaf. The body and variable
render at the containing depth. For lower-bound metrics $(h_l,w_l)$,
upper-bound metrics $(h_u,w_u)$, body metrics $(h_b,w_b,b_b)$, and variable
metrics $(w_v,b_v)$, the integral positions and parent metrics are [confirmed]

$$
\begin{aligned}
y_b &= \max(5,h_u), \\\\
s_l &= \max(5,h_l), \\\\
H &= y_b+h_b+s_l, \\\\
B &= y_b+b_b.
\end{aligned}
$$

The horizontal positions and width are:

$$
\begin{aligned}
x_b &= \max(w_l,w_u)+12, \\\\
x_v &= x_b+w_b+12, \\\\
W &= x_v+w_v+2, \\\\
y_v &= B-b_v.
\end{aligned}
$$

The lower bound begins at $(6,H-h_l)$, the upper bound at $(6,0)$, and the body
at $(x_b,y_b)$. The type-`0x22` record stores $H$, $W$, and $B$ in the words at
`+7`, `+9`, and `+0x0B`. The variable child uses render type `1`. [confirmed]

Twelve reset-origin traces cover unequal token-bound widths, a multi-token body,
a different variable, power, radical, fraction, and nth-root bodies, structural
bounds, and a nested integral. The JavaScript constructor matches every record
field and ID. It also reproduces all accepted LCD data writes through the outer
`34:660A` return. The traces supply comparison oracles, not constructor input.
[confirmed]

The type-`0x29` constructor maps summation source token `EF33h` through
`34:594D`. `34:4900` allocates the summation record, then reserves child leaves
for the variable, lower bound, upper bound, and body in that order. It fills
their payloads after all four reservations. Structural arguments therefore
allocate their records after the reserved leaves. A nested summation applies
the same rule recursively. [confirmed]

The variable, lower bound, and upper bound render one depth below the containing
leaf. The body renders at the containing depth. The variable leaf uses render
type `1`. For child height, width, and baseline metrics $(h,w,b)$, define
[confirmed]

$$
\begin{aligned}
L &= w_v+4+w_l, \\\\
O &= \max(w_u,L,12), \\\\
S_u &= \max(5,h_u), \\\\
S_l &= \max(h_v,h_l).
\end{aligned}
$$

Let $B_0=S_u+4$. The parent and body metrics are:

$$
\begin{aligned}
B &= \max(B_0,b_b), \\\\
y_u &= B-B_0, \\\\
y_l &= B+5, \\\\
y_b &= B-b_b, \\\\
H &= \max(y_l+S_l,y_b+h_b), \\\\
x_b &= O+6, \\\\
W &= x_b+w_b+5.
\end{aligned}
$$

The variable begins at $(0,y_l)$ and the lower bound begins at
$(w_v+4,y_l)$. Placing both on the common lower row keeps structural lower
bounds aligned with the variable. The upper bound begins at
$(\lfloor(O-w_u)/2\rfloor,y_u)$. The body begins at $(x_b,y_b)$. The
type-`0x29` record stores `3`, $H$, $W$, and $B$ at `+5`, `+7`, `+9`, and
`+0x0B`, respectively. [confirmed]

For ordinary five-row limits and a body whose baseline does not exceed $B_0$,
these equations reduce to $H=S_u+9+S_l$ and $B=S_u+4$. A reset-origin record
capture for
`sum(A,1,1,sqrt(int(1,3,N,A))//sqrt(A)^1^X)` exercises the taller-body branch.
The body stores $(h_b,b_b)=(33,18)$; the summation stores $(H,B)=(33,18)$,
places the upper limit at $y=9$, and places the lower row at $y=23$.
[confirmed]

Eleven reset-origin traces cover the representative `sum(N,1,3,N^2)` case,
unequal-width token limits, multi-token limits, power limits, radical,
nth-root, fraction, and power bodies, a different variable, and a nested
summation. The JavaScript constructor matches every record field and ID. It
also reproduces every accepted LCD data write through the outer `34:660A`
return. The traces supply comparison oracles, not constructor input.
[confirmed]

The settled lower-bound leaf for `sum(N,1,3,N^2)` contains `0x31`. The byte
pair `EF 1E` instead emits display code `0xF7`, the empty template square. It
appears in captures whose template navigation leaves a slot unfilled, including
discarded summation and `nDeriv(` captures. [confirmed]

The type-`0x23` constructor maps source token `0025h` through `34:594D`.
`34:4900` allocates the `nDeriv(` record, then reserves child leaves for the
variable, body, and evaluation value in that order. It fills those leaves
before it allocates structural descendants of the body or value. A nested
`nDeriv(` applies the same reservation rule recursively. [confirmed]

For body metrics $(h_b,w_b,b_b)$, variable metrics $(h_v,w_v)$, and
evaluation-value metrics $(h_e,w_e,b_e)$, the metric branches at `34:7485` and
the positioning branches at `34:76C2`–`34:76EF` produce [confirmed]

$$
\begin{aligned}
B &= \max(6,b_b,b_e-4), \\\\
x_v &= 5, \\\\
y_v &= B+2, \\\\
x_b &= 16, \\\\
y_b &= B-b_b, \\\\
x_e &= w_b+w_v+29, \\\\
y_e &= B+4-b_e.
\end{aligned}
$$

The record height is the union of all three positioned children, and the total
width ends after the evaluation value:

$$
\begin{aligned}
H &= \max(y_v+h_v,y_b+h_b,y_e+h_e), \\\\
W &= x_e+w_e.
\end{aligned}
$$

The type-`0x23` record stores `3`, $H$, $W$, and $B$ at `+5`, `+7`, `+9`,
and `+0x0B`. The variable leaf uses render type `1`. The valid settled scalar
case `nDeriv(X,X,1)` stores `0x58` in both the variable and body leaves. The
same body token precedes the type-`0x2A` marker in valid powered-body captures.
[confirmed]

Twelve reset-origin traces cover ordinary and unequal-width arguments, power,
radical, fraction, nth-root, and integral bodies, plus nested `nDeriv(`. The
JavaScript constructor matches every record field and ID. It also reproduces
every accepted LCD data write through the outer `34:660A` return. The traces
supply comparison oracles, not constructor input. [confirmed]

A further reset-origin trace covers a tall `logBASE(` body and a summation
evaluation value whose body contains a raised `logBASE(`. It proves the
small-row type-`0x28` constants and the $B+4-b_e$ evaluation-value placement.
The translated graph matches all 18 records and the final normalized
88-by-19-pixel entry bitmap. The synchronous renderer contributes 195 accepted
LCD writes. Their byte-column and row sequence matches the trace after removing
an eight-write timer interrupt. [confirmed]

`34:6C6B` adds the four-pixel glyph advance to logical pen positions `87`,
`91`, and `95`. `34:6C76` derives the one-past-right coordinate `96`.
The compare at `34:6C7C` draws the first two glyphs because their endpoints are
`91` and `95`; it skips the third glyph because its endpoint is `99`.
The JavaScript applies the same whole-glyph gate. [confirmed]

The interrupt reaches `run_indicator_tick` at `ram:027B` with
`indicCounter=1` and `indicBusy=0x78`. `01:6BBA` reloads the counter to `0x14`,
rotates the busy byte to `0x3C`, and rewrites pixel 95 across rows 0–7 as
`0,0,1,1,1,1,0,0`. Inserting this translated operation after the captured 28th
renderer operation reproduces all 203 accepted writes, including subsequent
read-modify-write bytes, with SHA-256
`1cd0a761fab7b948a1bd55cf47d627cdcab0c24620a2da0d3fe8204d1c3691a1`.
The insertion point is timer phase, not expression-tree state. Generated
expression timelines therefore keep this operation labeled as asynchronous UI
state. [confirmed]

Flat absolute-value bodies and expressions composed from ordinary token runs,
the native `Ans`, `sin(`, `cos(`, `tan(`, `ln(`, and `log(` tokens,
right-associated powers, $e^x$, $10^x$, `logBASE(`, radicals, nth roots,
stacked fractions, and numeric matrices now run from tokens through record
construction, layout, drawing operations, and LCD byte writes. Integrals,
summations, and `nDeriv(` compose with the same translated forms in their
arguments and in a stacked-fraction numerator. The remaining
arbitrary-expression branches are still untranslated.
[confirmed]

Each dispatch also captures the viewport origin at `ram:8DFE`/`ram:8E00`.
Nested fraction `1/2` reaches `34:5DA6` with the local rule `(1,6)`–`(5,6)`
and origin `(16,5)`. Page 4 therefore receives the translated endpoints
`(17,52)` and `(21,52)`. [confirmed]

The fixed 20-byte record header contains a two-byte ID at `+0`, a type byte at
`+2`, eight unaligned little-endian words at `+3`, `+5`, `+7`, `+9`, `+0x0B`,
`+0x0D`, `+0x0F`, and `+0x11`, and a byte at `+0x13`. The analyzer names words
by offset until each render type establishes its meaning. Words following the
root header are child IDs. `34:6CCD` passes an ID through `34:4B05` and
`34:4A83` to resolve the child record; these words are not RAM pointers.
[confirmed]

Exact point counts matter here. The resolver's `--funcs` mode groups an
instruction under the nearest preceding symbol. It places 69 instructions in
the `39:5167` bucket for each scenario even though the entry itself has zero
hits. `tools/test_hardware_trace.py` covers this distinction. [confirmed]

## Cell encoding

`eqdisp_emit_glyph` (`39:4E8E`) dispatches each `D:E` cell by its `D` byte:
`D=0x1F` is a cursor marker (no draw), `D=0x82` selects an indexed string or
title, and
otherwise a counted-string selection (`39:6B66` → `_KeyToString = 45CAh` → `01:6D10`,
`_KeyToString`, with its pointer table at `01:6E05`) or a direct glyph via
`39:4F1A` (`FC3C`–`FC40` → glyph `E - 0x3C + 5`,
`FE7D`–`FE81` → `E - 0x7D`, `E = 0x42` and `D < 0x0A` → glyph `D`). So `00C8` draws the literal name
"fnInt(", not a glyph. The full decode is in
`tools/cell-glyph-spec.md` and
`tools/token-name-spec.md`; the placement geometry
(`683D`, `6B1C`, `5167`/`5949`, pen conversion) is in
`tools/geometry-spec.md`. [confirmed]

## Trace replay and renderer checks

The renderer writes through the LCD ports rather than a RAM framebuffer.
`tools/trace_lcd.py` replays reset-origin TilEm TLMT v2 LCD I/O through the
pinned TilEm T6A04 state model, including mirrored ports, data reads, busy-write
rejection, and the controller's 128×64 backing RAM. This reconstructs the
emulator bitmap for a complete compatible trace; it is not a physical-controller
claim. The controller behavior is [standard] for the pinned TilEm source model;
synthetic tests confirm the replay implementation.

`tools/parity-mathprint.py` selects that replay when tracing is enabled.
The local ignored `tools/rom.bin` enables pinned-ROM reproduction when present.
For screenshot differentials, the tool also decodes the final RAM graph through
the `34:4ACE` and `34:4A83` walks above. It compares that calculator-decoded
semantic expression with the JavaScript graph before comparing pixels. A
dropped key or incomplete template exit therefore rejects the run instead of
appearing as a renderer mismatch. [confirmed]

The RAM oracle avoids an instruction trace for each fuzz case. TilEm still runs
the calculator to accept the key sequence and produce the screen, but the
ordinary case retains only a RAM dump and screenshot. A mismatched graph gets
retries at two slower key cadences. The final retry uses a `0.24`-second key
delay and a `0.12`-second inter-key wait. The depth-four seed-505 corpus has 20
calculator graphs matching their requested ASTs and 20 exact pixel matches. In
case 14, the first calculator entry omits native multiply token `82h`; the graph
check rejects that entry. A slower accepted graph contains the token and
matches the translated framebuffer. [confirmed]

The differential generator computes structural-record depth independently
from its syntactic generation depth. Calculator comparisons retain expressions
at depth four or below. Deeper generated ASTs remain valid inputs to the
JavaScript renderer, but the home-screen editor cannot construct their fifth
structural record through the path below. The optional
`--validate-entry-depth` run checks accepted depth-four and rejected depth-five
forms for every translated structural constructor. Seed `606` at generation
depth five rejects one over-limit candidate, replaces it, and produces 15 exact
decoded-graph and pixel matches with no inconclusive case. One long case needs
the final key-cadence retry. [confirmed]

A matrix-only seed-`815` corpus constructs numeric $1\times1$, $1\times2$, and
$2\times2$ literals, decodes the live RAM graph before evaluation, and compares
the translated type-`0x2B` render with the post-ENTER history block. Fourteen of
15 cases have exact decoded ASTs and pixels. The remaining 89-by-30 render is
inconclusive because the 96-by-64 history display exposes only 28 of its rows;
the harness rejects the clipped block instead of comparing it. This corpus
found the baseline-alignment error above. Its reduced mixed-baseline case now
matches every captured record field and all 1,264 framebuffer pixels.
[confirmed]

The browser's generated path encodes native calculator bytes, scans their
one- and two-byte token boundaries through translations of `34:58F9` and
`34:5911`, and splits nested arguments through the page-`34` parse-ahead state
machine at `34:5A99`–`34:5CAC`. The translation includes the public
`_AHEADEQUAL = 4B49h`, `_PARSAHEADS = 4B4Ch`, and `_PARSAHEAD = 4B4Fh`
entries plus the internal entries at `34:5AA3`, `34:5AA7`, and `34:5AA9`.
It constructs settled records and emits accepted LCD data bytes. Each
write replaces one eight-pixel span in a 96×64 framebuffer. Six changed and
deeply nested expressions pin every intermediate write and the packed final
framebuffer without loading a captured write stream. These deterministic cases
exercise summation, integral, `nDeriv(`, matrix, and a three-level raised
fraction. [confirmed]

The editable input
`int(1,3,(1//2)X,X)+int(1,3,(1//2)X,X)` has a 106-pixel expression endpoint.
The root record stores `112` at `+7`: the expression plus a six-pixel cursor
cell. Its child origins remain local at $x=0$, $16$, $56$, and $72$.
[confirmed]

The editor scrolls this record horizontally. `34:5DBE` adds the logical record
origin at `ram:8DFE` to each local $x$ coordinate. `34:5DC2` then subtracts the
horizontal clip at `ram:8E02`, and the admitted path at `34:5DE3` adds the
physical origin at `ram:8DFA`: [confirmed]

$$
x_{\mathrm{LCD}}
= x_{\mathrm{screen}}
{}+ x_{\mathrm{local}}
{}+ x_{\mathrm{record}}
{}- x_{\mathrm{clip}}.
$$

`34:5F5D` updates the clip for the cursor at the expression endpoint. The
traced editor state has a previous clip of $12$, a cursor width of $6$, and a
right bound of $95$. `34:5F87` stores the resulting clip $17$: [confirmed]

$$
x_{\mathrm{clip}}
= \max\left(x_{\mathrm{clip,old}},\;106+6-95\right)
= 17.
$$

The general path follows 16-bit instruction order. `34:5F61` first subtracts
the previous clip. A borrow clears `ram:8E02` and restores the unshifted
endpoint. Bit 3 of `(IY+44h)` selects a six-pixel cursor when set and a
five-pixel cursor when clear. The two callers add either zero or three more
pixels through `DE`. Both additions wrap as Z80 words before `34:5F7F`
compares the result with the low-byte right bound. Carry returns without a
store. Carry clear adds the remaining distance to the current clip and writes
it at `34:5F87`. An endpoint left of the previous clip can therefore clear the
clip, and an endpoint near `0xFFFF` can wrap before the bound comparison.
[confirmed]

The clip is editor state, not a function of the current width alone. If an edit
shrinks the 162-pixel three-integral record to the 106-pixel two-integral
record while `ram:8E02` is 73, `34:5F81` returns and retains 73. Shrinking the
record below 73 takes the borrow path at `34:5F64` and clears the clip.
[confirmed]

The web renderer carries this word across input events and applies the same
transition to both its full model metadata and its 96-pixel LCD writer. An
eight-integral boundary regression reaches a 442-pixel record and clip 353
without truncating its 127 native token bytes. This case is a deterministic
translation regression.

The vertical editor viewport is a separate word transition at
`34:5F8B`–`34:5FC0`. The routine reads the logical cursor top from `ram:8518`
and subtracts the previous clip at `ram:8E04`. A borrow at `34:5F96` clears the
old clip. Bit 3 of `(IY+44h)` selects a seven-row cursor when set and a five-row
cursor when clear. The live MathPrint redraw calls the routine first with
`DE=0`, then with `DE=4`. Both calls compare their wrapped 16-bit coordinate
with the low-byte bottom bound at `ram:8DFD`; carry returns without a store,
while carry clear advances `ram:8E04`. [confirmed]

A natural depth-four balanced fraction has record height 125, baseline 62,
cursor top 59, and bottom bound 62. The first pass changes the clip from 0 to
4. The second pass changes it from 4 to 8. The settled expression is therefore
translated upward by eight rows before the LCD writer applies the visible
window. `34:67C8`–`34:6872` rejects complete glyph cells above or below that
window and admits crossing cells for row clipping. [confirmed]

The translated LCD crop is 17×61 pixels and matches the calculator pixel for
pixel. Its SHA-256 is
`7516b14104afaa3259d45b4b1577d0a9ae96df4a9bbc65bb52b147e3cb59910d`.
`tools/mathprint-vertical-viewport-oracle.json` records the ROM, trace, RAM,
LCD-write, and crop hashes;
`tools/macros/mathprint-nested-fraction-vertical.macro` reproduces the natural
entry. [confirmed]

`34:6000`–`34:6015` appends the vertical editor chrome after the settled
expression. A nonzero `ram:8E04` clip calls bcall `53DAh`; its body at
`35:7116` draws the upper cue from the four rows at `35:717D`. `34:60A0` loads
the root height, subtracts one and the clip, and applies the same bottom-bound
comparison as `34:5DF8`. A remaining endpoint at or beyond the bound calls
bcall `53D7h`; `35:715B` draws the lower cue from `35:7182`. [confirmed]

The normal home editor centers both seven-pixel cells from the horizontal
bound at `ram:8DFC`, giving $x=44$. Their top rows are 0–3 and 58–61. The final
16 accepted writes in the natural trace exactly match the translated byte
columns, rows, values, and order. Appending them produces the complete 96×64
calculator LCD with zero pixel differences; its flat-byte SHA-256 is
`5e34c3710b0dbe45c5f8a8152fbc9db81ac098faa5698df429f5793ec6876d99`.
The 17×61 crop above deliberately excludes this separate chrome stream.
[confirmed]

The visible expression therefore begins at effective $x=-17$, while the cursor
cell begins at $x=89$. When `ram:8E02` is nonzero, `34:5FF2` calls `34:6031`.
That routine draws the seven-row left-overflow bitmap at `34:60B8` through
`34:61B2` after the expression. The translated expression plus this cue emits
198 accepted LCD writes. Their byte-column, row, and value triples match the
natural calculator redraw after removing the eight asynchronous right-cue
writes. The compact oracle is
`tools/mathprint-editor-overflow-oracle.json`; the reproduction input is
`tools/macros/mathprint-double-integral.macro`. [confirmed]

The centering path does not use an unbounded record height. In normal editor
mode, `34:753F` loads the root's `+07h` height word. `34:6043` substitutes the
one-byte bottom bound when the height has a nonzero high byte, and `34:604A`
does the same when its low byte exceeds the bound. Editor mode `49h` bypasses
the load and uses the bound directly. The natural combined-overflow case has
height 125, horizontal clip 15, vertical clip 8, and bottom bound 62, so the
cue occupies rows 28–34 instead of being centered off-screen. The translated
expression and all three overflow cues reproduce all 6,144 screenshot pixels.
`tools/mathprint-combined-viewport-oracle.json` pins the accepted graph, native
tokens, RAM state, write-stream hash, and full-LCD hash. [confirmed]

Glyph clipping precedes the font blitter. `34:6C5F` compares a glyph's left
edge with `ram:8E02`; the carry path at `34:6C69` reaches `34:6C81` and skips
the whole glyph while still advancing the logical pen. It does not draw the
suffix of a glyph that begins left of the viewport. The reset-origin expression
`(sqrt(X)*1^3)+(N^2+(X*A))` reaches this branch with the radical's `X` beginning
three pixels left of the visible edge. Applying the whole-glyph skip, followed
by the seven-row left-overflow cue, reproduces all 870 pixels of the cropped
87×10 calculator frame. [confirmed]

Root-hook bitmaps use the same display-unit gate. `34:630C` enters `34:6C37`,
whose bitmap header supplies a five-pixel advance before `34:6C5F` performs the
left-edge comparison. The reset-origin expression
`(sqrt(nDeriv(1,A,1)+11111))` reaches `34:6C69` with logical pen 6 and clip 7.
The subtraction produces `FFFFh` with carry, so the ROM omits the complete
five-pixel hook. The vertical stem and vinculum continue through `34:5D96` and
`34:5DA6`. Translating that unit skip reproduces all pixels in the cropped
87×15 calculator frame. `tools/mathprint-radical-viewport-oracles.json` pins
the input, trace, viewport state, branch witness, LCD writes, and final bitmap.
[confirmed]

Embedded records have an earlier whole-subtree gate. `34:6641`–`34:6655` adds
the embedded record's `+09h` width to the current logical pen and record origin,
then subtracts `ram:8E02`. Carry at `34:6659` skips the embedded renderer;
equality draws it. The reset-origin depth-four reproduction reaches the carry
path with logical endpoint 56 and clip 63, producing translated word `FFF9h`.
It omits the off-left nested power subtree while retaining its logical advance.
The translated record program removes the same two high-level operations and
still matches the calculator's 87×25 bitmap. Its flat-byte SHA-256 is
`b4a60c6f5b1bc78d5a59f6b6fb0f379c999e70dc09c409131677142c0c2b1b09`.
`tools/macros/mathprint-nested-depth4.macro` reproduces trace
`b8d970906e63db96d36847dfcafed91d97e73fc7699294cc8debd08e7affdd93`.
[confirmed]

The right-edge gate uses the same logical glyph advance. `34:6C6B`–`34:6C71`
adds the advance to the pen. `34:6C73`–`34:6C7A` derives the one-past-right
viewport coordinate, and `34:6C7C` skips the glyph when its endpoint is larger.
Equality draws the glyph, so an endpoint of `96` may occupy pixel 95. The
translated viewport applies both whole-glyph gates before rasterization.
[confirmed]

The eight writes inserted at instruction index 56 come from
`page_34:6CA8` → `ram:3CE1`. That call stack does not pass through `34:608F`, so
the stream is separate from the right-side bitmap path and remains outside the
settled expression timeline. [confirmed]

The actual `34:608F` path is observed elsewhere in the natural trace. `34:607A`
loads the wrapper record's `+09h` width, subtracts one, adds the logical origin,
and subtracts `ram:8E02`. Carry returns Z. A zero translated endpoint skips the
second decrement; otherwise `34:6089` decrements once more before `34:5DDB`
compares the word with the right bound. A value at or beyond the bound returns
NZ, so `34:5FFD` calls `34:608F`. The retained witness compares `HL=98` with
`DE=95` and takes that call. [confirmed]

`34:608F` places the four-pixel cue at physical screen origin plus right bound
minus four. Its writes update byte column 11 at rows 8–14 with `00`, `08`,
`0C`, `0E`, `0C`, `08`, and `00`. A fresh-clip home-editor redraw suppresses
this path for every 16-bit expression endpoint at physical origin zero;
shifted or retained-clip viewports still follow the complete selector. Cursor
blink separately writes `0x7C`
to byte column 11 on the same rows. The browser models the cue selector and
keeps the unrelated `34:6CA8` stream outside settled expression timelines.
[confirmed]

The text-cell path has a separate overflow boundary. `39:4F08` compares
`curCol` (`0x844C`) with `0x0F` before marker handling and calls the fixed-bank
`_EraseEOL` jump at `00:3CB7`. `39:6712` then sets `curCol` to `1`, emits the
`:` marker through `00:3FDB`, and gates subsequent display modes with `0x85E5`.
These page-`39` bytes do not control the page-`34` horizontal pixel clip above.
[confirmed]

The retained `sum(N,1,3,N)` trace exposes four calls through `34:5AA3` with
`C=1`. The scanner stops on the three depth-zero comma bytes. At the closing
`0x11` byte, it returns `A=0x11`, `DE=0xFF00`, and sets Z and C. The JavaScript
translation matches these registers, flags, and scratch bytes. Static byte
decoding covers the other mode bits and token classes; they do not yet have
independent dynamic coverage for every exit branch. [confirmed]

`34:5A05` classifies function openers from packed `D:E` tokens. Ordinary
one-byte tokens pass through `34:5A52`, `BB` tokens through `34:5A28`, and `EF`
tokens through `34:5A14`. The JavaScript scanner applies those comparisons and
ROM tables directly. Generic function runs can therefore contain translated
structural children without depending on a list of preview function names.
[confirmed]

Structural insertion through `34:473A` calls the bjump descriptor at
`ram:2E41`, whose body is `35:7B37`. The body reads the structural-depth byte
at `0x8DB6`, increments it modulo 256, and compares it with `0x05`. Input values
`0x00`–`0x03` preserve `A` and return with carry clear. Values `0x04`–`0xFE`
return `A=0x03` with carry set. Input `0xFF` wraps to zero and takes the
carry-clear path. The caller sends carry set through `34:473F` to `34:54D2`,
which sets `(IY+45h).6` and writes `0x05` to `0x9D20`. [confirmed]

A normal POWER insertion reaches the gate with `A=0x2A`. The depth-four trace
enters with depth byte `0x03`, increments it to `0x04`, and returns through
`34:4744` to insert the record. The depth-five trace enters with `0x04`, returns
`A=0x03` with carry set, and reaches `34:54D2`. The reproduction macros are
`tools/macros/mathprint-depth4-power-accept.macro` and
`tools/macros/mathprint-depth5-power-reject.macro`; their trace SHA-256 values
are `66c3c43dc306cbf43ba9579171824f180faff7377a23f33b584e07bf5dba78d5`
and `b8355cb4a58eb2f0a97dd17238e900705c20c5d99ab80f60ee16aa1f876e1f3a`.
`tools/mathprint-depth-limit-oracle.json` records the branch states. [confirmed]

Paired calculator runs place power, fraction, radical, nth-root, absolute,
integral, summation, `nDeriv(`, $e^x$, $10^x$, and log-base at the same
boundary. All 11 depth-four forms produce the requested decoded graph and
pixel-exact JavaScript frame. All 11 depth-five forms reject the requested
record. This is a calculator-entry limit; it does not limit programmatically
constructed JavaScript ASTs or decoded record graphs. [confirmed]

`EF36h` also takes this gate. `34:5935` maps it to type `0x2C`, and `34:4690`
branches through `34:473A` instead of using a row at `34:59AC`. The accepted
gate path preserves `A=0x2C`; the rejected path returns `A=0x03` as above.
[confirmed]

Below the cap, `34:58A0` inserts `EF 2C 00 00 EF 2D`. `34:4862` allocates the
type-`0x2C` record and patches its ID into the marker. The allocator at
`33:4F42` supports types `0x1F`–`0x2B`; type `0x2C` indexes the adjacent bytes
at `33:4FA9`. Those bytes produce `E=0x42`, `BC=0x0002`, and `HL=0x0018`.
In the first observed context, the allocator creates record ID `8` with parent
ID `7` and this 20-byte header: [confirmed]

```text
08 00 2C 07 00 01 00 06 00 03 00 00 00 00 00 06 00 01 00 EF
```

The parent leaf marker changes from `EF 2C 00 00 EF 2D` to
`EF 2C 08 00 EF 2D`. Construction returns normally through `34:547E`.
The terminal failure occurs during geometry calculation. `34:7609` indexes the
13-word table at `34:7611` with type `0x2C` and reads the code bytes at
`34:762B` as the word `3BCDh`. The dispatcher calls `ram:3BCD`, whose bjump
reaches `03:467F`. That routine returns through the dispatcher's extra stack
word to `ram:0002`, entering the reset path through `ram:028C` and `3F:412C`.
The JavaScript translation reports this reset boundary and does not define
type-`0x2C` metadata, geometry, or rendering support. [confirmed]

The English external token table names `EF37h` `MATHPRINT` and `EF38h`
`CLASSIC`; it has no `EF36h` entry. These names come from the
[TI-Toolkit token sheet](https://github.com/TI-Toolkit/tokens), not from the
ROM-local control-flow trace. [hypothesis]

The first byte of each row at `34:59AC` selects a scan policy at `34:5678`.
Scan kind `3` enters `34:56E3` with `B=2` and selects one unary child. Scan kind
`4` enters `34:56EC` with `C=1` for each source argument. The remaining
nonzero metadata bytes map source arguments to child-record indices. They are
`[3,4,1,2]` for integral, `[2,1,3]` for `nDeriv(`, `[2,1]` for `logBASE(`,
and `[4,1,2,3]` for summation. The JavaScript scanner returns each half-open
source-byte range with its child index and verifies the terminating comma or
`0x11` byte. The retained summation trace reaches `34:56EC` four times and
matches those ranges. [confirmed]

Scan kind `1` enters `34:5699` for `F0h` power and `F1h` nth-root operators.
It saves the source cursor, returns an operand endpoint in `BC`, and restores
the source cursor at `34:56AC`–`34:56B3`. `X^12` returns after both digit
bytes. The `2^(X^(2³))` editor buffer contains explicit `10h`–`11h` raised
slots; separate calls return the outer and inner closing-slot endpoints. The
JavaScript scanner translates these numeric and delimited-slot branches and
requires native construction to stop at the same half-open byte boundary.
The `X^Ans` buffer stores `58 F0 10 72 11`; the `X^L1` buffer stores
`58 F0 10 5D 00 11`. Both traces take `34:56BF` and return the byte after the
closing `11h`. Raw native bytes for these one- and two-byte named operands now
reproduce the captured record graphs and complete accepted LCD writes.
`34:580C` also admits direct letters, `Ans`, list, matrix, and string names,
`π`, `BB31h`, and bounded `5Fh`/`EBh` names. The JavaScript translation applies
the classifier and bounded name loop directly. It groups a name designator and
its accepted bytes as one expression atom, so a raised name ends at the same
half-open byte boundary as the ROM scan. [confirmed]

Scan kind `2` enters `34:56DF` → `34:5795` for the `EF2Eh` and `EF2Fh`
stacked-fraction operators. It rewinds to the numerator, calls `34:5AA7` with
`B=14h`, and returns the operator's `EFh` byte in `BC`. A second scan selects
the denominator range. The wrapper at `34:57A1`–`34:57C1` distinguishes
nesting depth in `D`, unwound boundary count in `E`, and the saved depth byte
at `ram:9D05`. The JavaScript scanner retains these results and verifies both
operand ranges before constructing a type-`0x20` record. Leaf, powered,
nested-denominator, and raised-fraction cases cover the translated branches.
[confirmed]

Scan kind `6` enters `34:568A` for each matrix element. Native matrix values
use `06h` and `07h` square-bracket tokens for the outer container and each row.
`34:57C2` reads the current element token, rewinds `ram:965D` by one byte, and
then `34:5AA7` scans with `B=20h`. The returned `BC` points to a depth-zero
`2Bh` comma or the row-closing `07h`. The `0x9D05` result is `0` for a comma
and `FFh` for the row close. The JavaScript scanner retains these results and
derives row-major element ranges. Retained $1\times1$, $1\times2$,
$2\times3$, and $3\times3$ value traces pin primitive numeric cells. A
$2\times2$ trace with `sqrt(2)` and $X^2$ pins the structural-cell path. At
`34:5BA7`, `B=20h` makes a function opener increment `D`. Its closing `11h`
sets bit 6 in `B`, resumes the scan, and reaches the matrix delimiter. The
JavaScript parse-ahead translation applies that branch to ordinary, `BB`, and
`EF` opener classes. [confirmed]

When a fraction appears inside a matrix element or another delimited argument,
the direct `34:5795` scan can pass the enclosing `07h` or `11h` delimiter. The
translated parser intersects that scan endpoint with the active kind-`6` or
structural-argument boundary before constructing the child record. [confirmed]

The browser expands every accepted byte into eight ordered pixel results. A
timeline row records the previous byte, replacement byte, all eight destination
bits, and which bits changed. Accepted writes with equal previous and replacement
bytes therefore remain visible in the trace. [confirmed]

The text field uses a preview-specific semantic grammar for ordinary input. It
does not drive the TI-OS editor state machine. The ROM engine separately
decodes a captured live editor arena, active gap leaf, and cursor into a semantic
tree and translates ordinary packed-token insertion, in-leaf navigation, and
packed-token deletion on that state. The browser
does not yet expose the mutation API as an interactive calculator editor. An
input prefixed with `hex:` bypasses the preview grammar and passes the
listed native bytes to the translated constructor. Malformed streams and
untranslated structural types produce an error; this path does not select the
model compositor. Each accepted LCD byte remains available as eight ordered
pixel results in the live timeline. [confirmed]

The 5,019-case Node test remains a deterministic parser/layout smoke test. Six
settled record programs provide exact final-pixel and complete accepted-write
parity for their expressions. Three fresh absolute-value cases, four power
cases, eight power/radical composition cases, four nth-root cases, thirteen
fraction cases, twelve integral cases, and eleven summation cases verify
token-to-record construction and complete accepted-write streams. Four
exponential cases and four `logBASE(` cases verify their child metrics, nested
structures, and accepted-write streams. Twelve `nDeriv(` cases verify its three
arguments, structural bodies, and recursive nesting. Six raised multi-argument
numerator cases also require the settled record graph to decode to the asserted
semantic expression. Three nested-baseline cases verify depth-sensitive
`logBASE(` placement and the per-structure `+0x0F` adjustment. Five grouping
cases cover flat and structural groups, grouped power operands, and a structural
absolute-value child. The deepest power oracle has three raised levels. Six named-token cases verify counted
spellings, raised small-font widths, compound parentheses, structural children,
and complete accepted-write streams. Five two-byte-token cases verify list,
matrix-name, equation-variable, and string-variable tables in large and raised
contexts. Two native-list cases verify `08h`/`09h` parsing, brace geometry,
baseline-sensitive stretching, and semantic graph decoding. Two longer trace
scenarios cover the editor and display activity
around the final key press.
[confirmed]

`tools/fuzz-mathprint-diff.py` builds a semantic expression tree, encodes its
native calculator bytes, constructs the translated record graph, and compares
the resulting pixels with a reset-origin TilEm screenshot produced from the
corresponding key sequence. It does not compare the calculator with the preview
compositor. Each run uses a new emulator state file. Adjacent equal keys receive
an explicit scan delay. Integral and summation templates receive rebuild delays
after menu selection and each slot transition. A pixel mismatch triggers an
instruction trace for branch and LCD-write diagnosis; exact cases do not pay
the trace cost.
Trace-limit cases leave the screenshot mismatch intact and report only the
trace diagnosis as inconclusive. [confirmed]

The opt-in generic-function domain wraps arbitrary admitted trees in the
single-byte `sin(`, `cos(`, `tan(`, `ln(`, and `log(` tokens. Their arguments
include nested functions and every structural constructor accepted by the
depth-four entry gate. Seed 917 at depth four produces 20 calculator inputs;
all 20 translated LCD bitmaps match their reset-origin screenshots exactly.
The corpus includes the left-clipped radical case
`log(sqrt(int(3,1,nDeriv(1,A,3),N)))`. [confirmed]

The opt-in list domain wraps two arbitrary admitted trees in native `08h` and
`09h` tokens. It types the braces with **[2nd]** **(** and **[2nd]** **)**, then
compares the decoded element tree and pixels. List containers do not allocate a
structural record, but structural elements still contribute to the depth-four
entry gate. [confirmed]

`34:62D0` selects seven root-hook rows when `ram:8515` is zero and five rows
when it is nonzero. The routine subtracts that row count from the radical
height and returns the difference in `DE`. `34:62A7` decrements `DE` before
`34:62AE` passes the vertical stem to `34:5D96`. The stem endpoint is therefore
$h-8$ for the seven-row hook and $h-6$ for the five-row hook. In the
tall-summation input above, the final trace reaches `34:62D0` with
`ram:8515=2`, radical height 17, and stem endpoint 11. Translating the returned
word removes the final two-pixel difference from the reset-origin screenshot.
[confirmed]

## Extracted records and interactive model

The class table, decoded handler records, and selected descriptors are extracted to
`web/mathprint/layout.json` by `tools/export-layout.py`;
the fonts to `web/mathprint/font.json` by `tools/export-font.py`; and the
single- and two-byte token spellings to
`web/mathprint/token-strings.json` by `tools/export-token-strings.py`. The font
data appears on the interactive
renderer's font-table tab. `tools/interp-cells.js` and the browser share the executable
translations in `web/mathprint/rom-engine.js`. The translated routines consume
`layout.json` for handler lookup, row-cell iteration, direct glyph and delimiter
classification, descriptor iteration, fraction endpoints, and class-6 row
stepping. `web/mathprint/record-programs.json` contains six retained record
snapshots for offline comparison. The browser does not fetch them. Closed
expressions accepted by the native constructor use the translated record graph
and primitive stream for both the generated LCD view and the model view.
Partial, unsupported, and over-wide text keeps the separate trace-fitted box
compositor so the editor can continue to display incomplete input. It constructs
supported named-token, absolute-value, power,
radical, nth-root, stacked-fraction, integral, summation, and `nDeriv(`
expressions from native token bytes, including nesting among the structural
forms. The translated renderer exposes every generated LCD byte and the
resulting pixel frame as a live timeline. This mode does not load a record
fixture or captured LCD event stream. Multi-argument and generic-function
boundaries pass through the translated `34:5AA3` state machine. Numeric and
delimited raised operands also pass through the translated `34:5699` scan, and
stacked-fraction operands pass through the translated `34:5795` scan. The
remaining source grammar and record-construction branches are listed above.
[confirmed]

The standalone nth-root encoder supplies an inferred template boundary because
the retained trace does not expose the final source buffer. [hypothesis]
