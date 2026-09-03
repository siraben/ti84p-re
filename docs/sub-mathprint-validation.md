# MathPrint validation and browser model

*TI-84 Plus OS 2.55MP — how the standalone renderer is checked against the ROM.*

The standalone renderer in `web/mathprint` is checked against the ROM at
several boundaries: pinned-byte interpreters, captured LCD streams, settled
traces, and browser-level behavior. This page lists that verification stack
and states where the browser model stops claiming ROM parity. The mechanisms
being verified are described in [Equation display
(MathPrint)](sub-equation-display.md) and [MathPrint live editor and settled
drawing](sub-mathprint-editor.md).

## Validation and renderer checks

No single comparison establishes parity. The verification stack deliberately
checks increasingly large boundaries:

| Check | Compares | What it establishes |
|-------|----------|----------------------|
| Pinned-byte differential | JavaScript transition against the corresponding ROM helper bytes | Closed helper branches, flags, and wrap behavior. |
| Decoded-graph oracle | Requested AST against the calculator's RAM record graph | The calculator accepted the intended expression structure. |
| Accepted-write oracle | Ordered LCD `(column, row, value)` tuples | Construction and draw order, including accepted writes that do not change a byte. |
| Final-bitmap differential | Generated 96×64 pixels against TilEm | Visible parity, but not operation order by itself. |
| Fuzz run | Native tokens through calculator RAM and screen against the translated graph and frame | Composition across supported constructors. |

### From LCD writes to pixels

The renderer writes through the LCD ports rather than a RAM framebuffer.
`tools/ti84re/trace/lcd.py` replays reset-origin TilEm TLMT v2 LCD I/O through the
pinned TilEm T6A04 state model, including mirrored ports, data reads, busy-write
rejection, and the controller's 128×64 backing RAM. This reconstructs the
emulator bitmap for a complete compatible trace; it is not a physical-controller
claim. The controller behavior is [standard] for the pinned TilEm source model;
synthetic tests confirm the replay implementation.

`tools/ti84re/mathprint/parity.py` selects that replay when tracing is enabled.
The local ignored `tools/rom.bin` enables pinned-ROM reproduction when present.
For screenshot differentials, the tool also decodes the final RAM graph through
the `34:4ACE` and `34:4A83` walks in [Equation display
(MathPrint)](sub-equation-display.md#page-34-expression-records). It compares that calculator-decoded
semantic expression with the JavaScript graph before comparing pixels. A
dropped key or incomplete template exit therefore rejects the run instead of
appearing as a renderer mismatch. [confirmed]

### RAM and AST differential oracles

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
found the baseline-alignment error. Its reduced mixed-baseline case now
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

### Horizontal viewport

The editable input
`int(1,3,(1//2)X,X)+int(1,3,(1//2)X,X)` has a 106-pixel expression endpoint.
The root record stores `112` at `+7`: the expression plus a six-pixel cursor
cell. Its child origins remain local at $x=0$, $16$, $56$, and $72$.
[confirmed]

The editor scrolls this record horizontally. `34:5DBE` adds
`eqdispViewport.logical_x` to each local $x$ coordinate. `34:5DC2` then
subtracts `eqdispViewport.horizontal_clip`, and the admitted path at `34:5DE3`
adds `eqdispViewport.physical_x`: [confirmed]

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

### Vertical viewport

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

The glyph gate continues to the lower-edge comparison after an accepted
upper-edge crossing. `34:6807` stores the number of rows above the window in
`0x9D01`. Raised glyphs add their leading padding-row skip at `34:6848`–`34:684C`.
An endpoint below the lower edge stores the explicit row count in `0x9B72` at
`34:683A`–`34:683F`. Bit 0 of `(IY-1)` marks an active source-row skip, bit 1
marks a rejected glyph, and bit 7 of `(IY+32h)` marks an active row-count byte.
A viewport shorter than the glyph can therefore clip both edges in one call.
[confirmed]

The finite model partitions every logical-top word, vertical-clip word, and
render-depth byte at the MathPrint bottom bound `0x3E`. Its 16 path classes
cover 1,099,511,627,776 projected states. Pinned-byte differential tests also
exercise 229,456 boundary states across nine byte-sized bounds, including word
wrap and dual-edge clipping. [confirmed]

The translated LCD crop is 17×61 pixels and matches the calculator pixel for
pixel. Its SHA-256 is
`7516b14104afaa3259d45b4b1577d0a9ae96df4a9bbc65bb52b147e3cb59910d`.
`tools/oracles/mathprint/mathprint-vertical-viewport-oracle.json` records the ROM, trace, RAM,
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
`tools/oracles/mathprint/mathprint-editor-overflow-oracle.json`; the reproduction input is
`tools/macros/mathprint-double-integral.macro`. [confirmed]

The centering path does not use an unbounded record height. In normal editor
mode, `34:753F` loads the root's `+07h` height word. `34:6043` substitutes the
one-byte bottom bound when the height has a nonzero high byte, and `34:604A`
does the same when its low byte exceeds the bound. Editor mode `49h` bypasses
the load and uses the bound directly. The natural combined-overflow case has
height 125, horizontal clip 15, vertical clip 8, and bottom bound 62, so the
cue occupies rows 28–34 instead of being centered off-screen. The translated
expression and all three overflow cues reproduce all 6,144 screenshot pixels.
`tools/oracles/mathprint/mathprint-combined-viewport-oracle.json` pins the accepted graph, native
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

### Nested clipping

The subtraction produces `FFFFh` with carry, so the ROM omits the complete
five-pixel hook. The vertical stem and vinculum continue through `34:5D96` and
`34:5DA6`. Translating that unit skip reproduces all pixels in the cropped
87×15 calculator frame. `tools/oracles/mathprint/mathprint-radical-viewport-oracles.json` pins
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

The `logBASE` prefix is a counted string, not one viewport unit. `34:6C26`
loads one display code, `34:6C2A` calls the ordinary glyph path, and the
`DJNZ` at `34:6C2F` repeats for the remaining codes. The word pen advances
after a skipped code, so `l` may be left of the clip while `o` and `g` draw;
the last code may likewise be rejected at the right edge without partially
drawing it. The translated editor expands the `6Ch 6Fh 67h` string into three
ordered glyph calls before applying either viewport gate. An exact finite
model partitions every initial pen word and clip word for both the root widths
`6,6,6` and the raised widths `3,4,4`, including pen wrap. [confirmed]

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

### Text overflow and structural depth

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
`tools/oracles/mathprint/mathprint-depth-limit-oracle.json` records the branch states. [confirmed]

Paired calculator runs place power, fraction, radical, nth-root, absolute,
integral, summation, `nDeriv(`, $e^x$, $10^x$, and log-base at the same
boundary. All 11 depth-four forms produce the requested decoded graph and
pixel-exact JavaScript frame. All 11 depth-five forms reject the requested
record. This is a calculator-entry limit; it does not limit programmatically
constructed JavaScript ASTs or decoded record graphs. [confirmed]

`EF36h` also takes this gate. `34:5935` maps it to type `0x2C`, and `34:4690`
branches through `34:473A` instead of using `eqdisp_child_scan_table`. The accepted
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

### Source grammar boundaries

The English external token table names `EF37h` `MATHPRINT` and `EF38h`
`CLASSIC`; it has no `EF36h` entry. These names come from the
[TI-Toolkit token sheet](https://github.com/TI-Toolkit/tokens), not from the
ROM-local control-flow trace. [hypothesis]

The first byte of each `eqdisp_child_scan_table` row selects a scan policy at
`34:5678`.
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

### Browser model and fuzz domains

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

`tools/ti84re/mathprint/fuzz_diff.py` builds a semantic expression tree, encodes its
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

## Browser model and current boundary

Closed supported expressions use the translated record graph. The browser does
not replay a record fixture or captured LCD stream for this path. Partial or
unsupported editor text remains a separate preview mode and is not presented
as ROM parity. [confirmed]

| Browser path | Input | Output | Boundary |
|--------------|-------|--------|----------|
| Translated ROM path | Supported complete native expression | Record graph, primitive stream, ordered LCD writes, and pixels | Untranslated source or constructor branches fail explicitly. |
| Live-arena decoder | Captured arena, active gap leaf, and cursor | Cursor-annotated semantic AST | Does not predict every next key mutation. |
| `hex:` path | Explicit native bytes | Translated construction and render result | Malformed or unsupported forms report an error. |
| Fallback compositor | Partial or unsupported preview text | Approximate editable boxes | Not a ROM-parity claim. |

The class table, decoded handler records, selected descriptors, and page-7
display-byte tables are extracted to `web/mathprint/layout.json` by
`tools/ti84re/mathprint/export_layout.py`;
the fonts to `web/mathprint/font.json` by `tools/ti84re/mathprint/export_font.py`; and the token,
`_KeyToString`, and inline cell strings to `web/mathprint/token-strings.json`
by `tools/ti84re/mathprint/export_token_strings.py`. The font
data appears on the interactive
renderer's font-table tab. `tools/js/interp-cells.js` and the browser share the executable
translations in `web/mathprint/rom-engine.js`. The translated routines consume
`layout.json` for handler lookup, row-cell iteration, direct glyph selection,
archived fixed-token lookup, display-byte remapping, descriptor iteration, fraction
endpoints, and class-6 row stepping. `web/mathprint/record-programs.json`
contains six retained record
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
remaining source grammar and record-construction branches are listed in
[MathPrint pipeline coverage](sub-equation-display.md#mathprint-pipeline-coverage).
[confirmed]

The standalone nth-root encoder supplies an inferred template boundary because
the retained trace does not expose the final source buffer. [hypothesis]
