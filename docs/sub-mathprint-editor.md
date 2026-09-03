# MathPrint live editor and settled drawing

*TI-84 Plus OS 2.55MP — from the gap buffer to settled pixels.*

This page follows one edit through the MathPrint editor: the gap buffer,
the record graph, marker rendering, the page `39` argument layout, and the
settled drawing that reset-origin traces pin byte for byte. It continues
[Equation display (MathPrint)](sub-equation-display.md), which defines the
records, handlers, and cell geometry used here.

## Live editor reconstruction

The coverage report in [Equation display
(MathPrint)](sub-equation-display.md#mathprint-pipeline-coverage) says which
observations support the recovered logic. This page changes viewpoint: it follows an edit from the gap buffer,
through the record graph, and back to pixels. [confirmed]

### Gap buffer and record regions

The four editor pointers describe two live byte ranges separated by unused
space:

```c
typedef struct {
    uint16_t top;       /* editTop: first address of the left segment */
    uint16_t cursor;    /* editCursor: one past the left segment */
    uint16_t tail;      /* editTail: first address of the right segment */
    uint16_t bottom;    /* editBtm: one past the right segment */
} MathPrintEditorGapPointers;

/* Logical payload = [top, cursor) followed by [tail, bottom). */
```

The record-region pointers form a second typed block. Fields that remain
unresolved keep address-based names: [confirmed]

```c
#pragma pack(push, 1)
typedef struct {
    uint16_t structural_begin;   /* 0x8DAF */
    uint16_t extended_leaf_end;  /* 0x8DB1 */
    uint8_t unknown_04[9];
    uint16_t leaf_begin;         /* 0x8DBC */
    uint16_t leaf_end;           /* 0x8DBE */
    uint16_t unknown_11;
    uint16_t active_leaf;        /* 0x8DC2 */
} MathPrintArenaState;
#pragma pack(pop)
```

The in-progress editor is a gap buffer. `editTop` (`0x96F4`) and `editCursor`
(`0x96F6`) bound the left segment. `editTail` (`0x96F8`) and `editBtm`
(`0x96FA`) bound the right segment. Moving across a structural object exposes
the six-byte right-segment marker `EF type id_lo id_hi EF 2D`. An insertion at
that boundary makes the metric walker enter `34:759C` with its parsed pointer
at `editTail + 6`. The comparison at `34:75A1` then returns Z, so `34:75A5`
falls through. [confirmed]

The live expression graph spans two record regions.
`eqdisp_find_structural_record` starts at `mathprintArenaState.structural_begin`
and stops at `mathprintArenaState.leaf_begin`. `34:4AF0` advances by the
structural record size. The child words after each 20-byte header remain record
IDs. `eqdisp_find_leaf_record` starts its leaf-record walk at
`mathprintArenaState.leaf_begin`. It normally uses
`mathprintArenaState.leaf_end` as the boundary. Bit 2 of `(IY+1)` instead
selects `mathprintArenaState.extended_leaf_end`. [confirmed]

`eqdisp_substitute_active_leaf` handles the active gap during that leaf walk.
When the gap bit is set and the current record equals
`mathprintArenaState.active_leaf`,
`34:4ABF` substitutes
`editBtm` as the next record pointer. Every other leaf advances by its 19-byte
prefix plus the payload length at `+0x11`. The active record's logical payload
is the concatenation of `editTop`–`editCursor` and `editTail`–`editBtm`.
This explains why a RAM dump can hold structural headers below the entry,
the active leaf in the gap, and later leaf records near the top of RAM.
[confirmed]

Four reset-origin RAM snapshots pin the cursor-to-record mapping. The compact
bytes and expected trees are in `tools/oracles/mathprint/mathprint-editor-gap-oracles.json`.
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

### Ordinary token insertion

Ordinary token insertion follows `34:4775–47A4` into `34:4BB9–4C0D`. The
non-structural branch reaches the page-6 gap writer through `00:3699`.
`06:4341–4388` checks available space, stores the one- or two-byte packed token
at `editCursor`, and advances the pointer. In the captured root-leaf transition,
the write at `06:437A` stores `32h` at `9DE1h`; `06:437C` then changes
`editCursor` from `9DE1h` to `9DE2h`. [confirmed]

`tools/oracles/mathprint/mathprint-editor-mutation-oracles.json` retains two adjacent pre/post
transitions and one five-write sequence. Appending `2` after root token `1`
changes the active payload from `31h` to `31h 32h`. Inserting `2` into an empty
fraction numerator advances the right gap boundary past `EF 1E`, so the token
replaces the empty slot. The fraction transition also shows that the
type-`0x20` record keeps `EFh` at `+13h` instead of recomputing that byte from
the new `32h` numerator. The editor AST therefore retains structural `+13h`
state in addition to the active leaf's `+0Fh` and `+11h` words. [confirmed]

The five-write sequence enters `08 08 31 09 09`, the native bytes for `[[1]]`.
Wrapper record `6` continues to point directly to leaf record `7`; the live
arena allocates no structural record. After the first and second writes, the
decoder retains one and two unfinished list frames around the cursor. The first
`09h` closes the inner frame into a one-element list. The second closes the
outer frame into a list whose element is that inner list. The settled
type-`0x2B` matrix record belongs to the later dimensioned construction path,
not these five live gap writes. [confirmed]

`editorInsertPackedToken()` consumes the decoded arena, writes the active leaf
payload, and decodes the graph again. All five `[[1]]` transitions match the
post-key cursor tree, every reconstructed record field, and the complete
cursor-off 96×64 LCD bitmap. Directly appending the byte to the previous
semantic tree would miss four of the five regrouping transitions. Cursor
navigation is tested separately below. [confirmed]

### Structural template insertion

Most structural insertions share the same transaction. A small type policy
decides which packed token, if any, moves into a child and which child receives
the cursor:

```pseudocode
\begin{algorithm}
\caption{Insert a structural template}
\begin{algorithmic}
\STATE $rule \gets \operatorname{TemplateRule}(renderType)$
\STATE split the active leaf at the cursor on a packed-token boundary
\STATE consume one token on the right when $rule$ requires replacement
\STATE write placeholder \texttt{EF type 00 00 EF 2D} into the containing leaf
\STATE allocate the structural record and its ordered child leaves
\STATE patch the marker with the allocated record ID
\STATE distribute the left payload according to $rule$
\STATE select $rule.initialChild$ and install its gap payload
\STATE remeasure ancestors while retaining editor-only record fields
\end{algorithmic}
\end{algorithm}
```

The policy table makes the structural differences explicit. “Initial focus”
describes blank insertion; leading, mid-leaf, and leaf-end cases can migrate
payload or choose a different child as described below. [confirmed]

| Source token | Type | Ordered children | Initial focus |
|--------------|-----:|------------------|---------------|
| `EF2Eh` | `0x20` | numerator, denominator | numerator |
| `00B2h` | `0x21` | enclosed expression | enclosed expression |
| `0024h` | `0x22` | lower bound, upper bound, body, variable | lower bound |
| `0025h` | `0x23` | variable, body, evaluation value | variable |
| `00F1h` | `0x24` | index, radicand | radicand, with `Ans` as the index |
| `00BFh` / `00C1h` | `0x25` / `0x26` | exponent | exponent |
| `00BCh` | `0x27` | radicand | radicand |
| `EF34h` | `0x28` | base, argument | base |
| `EF33h` | `0x29` | variable, lower bound, upper bound, body | variable |
| `00F0h` | `0x2A` | exponent; base precedes the marker | exponent |

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
match the calculator. The constructor also returns that decoded arena directly,
so a following translated edit does not need to import RAM again. [confirmed]

Fraction insertion exposes the four cursor classes most clearly:

| Cursor state before insertion | New numerator | Bytes retained after the marker | Selected child |
|-------------------------------|---------------|---------------------------------|----------------|
| Blank root | `EF 1E` | none | numerator |
| After `1` | `1` | none | denominator |
| Between `1` and `2` | `1` | `2` | denominator |
| Before `12` | `EF 1E` | `12` | numerator |

The migrated leaf keeps editor-only header state: the leaf-end case retains
`word0F = 0` and `word11 = 1`. In a nested example, outer records `8`–`10`
remain in place while the allocator appends fraction `11` and children `12`
and `13`; the left payload migrates to child `12`, and structural depth advances
from one to two. Rebuilding the semantic tree from scratch would lose these
record identities. [confirmed]

Natural-input oracles cover all four cursor classes at the root and in both
children of an outer fraction. In every case the translated cursor AST,
record fields, ancestor metrics, and all 768 LCD bytes match the calculator.
Deeper fraction positions remain open. [confirmed]

Integral, `nDeriv(`, summation, log-base, and the one-child forms join the
shared marker path at `34:5057`, then allocate at `34:4862–34:492B`.
One-child forms also pass through `34:5473` and `34:58A0`. Multi-argument forms
reserve their child IDs in the table order above, initialize every child with
`EF 1E`, and select the first child. The three captured permutations therefore
distinguish integral `(lower, upper, body, variable)`, derivative
`(variable, body, value)`, and summation `(variable, lower, upper, body)`.
[confirmed]

Across these forms, blank and leaf-end insertion retain the payload to the
left of the cursor; leading and mid-leaf insertion replace one complete packed
token on the right. Root-level natural captures cover all four cursor classes
and match the decoded cursor AST, every record field, and all 768 LCD bytes.
The blank derivative variable is visually distinctive: it adds two pixels
between the derivative fraction and body, repeats after the evaluation bar,
and renders `EF 1E` as a solid five-pixel focus box. [confirmed]

The nth-root route is separate: `34:504F` enters `34:51C0–51D9`, then reaches
`34:5473`, `34:58A0`, and the three-record allocator at `34:4862`.

Blank-root insertion places `Ans` (`72h`) in the index child and `EF 1E` in the
radicand child. The cursor enters the radicand. Leaf-end and mid-leaf insertion
move the payload left of the cursor into the index. Leading insertion creates
blank index and radicand children and enters the index. Leading and mid-leaf
insertion replace the packed token immediately to the cursor's right.
`tools/oracles/mathprint/mathprint-editor-structural-mutation-oracles.json` captures the four
states. The translated AST, every record field, and all 768 LCD bytes match
their calculator states. [confirmed]

Source token `F0h` maps to postfix-power type `0x2A` through
`eqdisp_source_type_table`. The editor
dispatcher enters `34:50EF–511D`, then joins the shared marker and allocation
path at `34:5057`. Blank-root insertion supplies `Ans` (`72h`) as the base.
Leaf-end and mid-leaf insertion bind the atom immediately left of the cursor.
Leading insertion has no base and replaces the packed token immediately to the
cursor's right. [confirmed]

The leading state contains `EF 2A id_lo id_hi EF 2D` without a preceding base.
It is valid while the editor gap is active, and the LCD draws the exponent
cursor above an empty base position. The JavaScript graph uses an editor-only
`emptyPowerBase` node for this state. Settled graph decoding continues to reject
a postfix-power marker without a base. Four reset-origin captures cover every
root cursor class and match the cursor AST, every record field, and all 768 LCD
bytes. [confirmed]

When the gap precedes an existing structural marker, `34:58A0–58B4` inserts
the new six-byte marker without consuming the old one. Seven natural captures
apply the one-child, nth-root, power, log-base, integral, `nDeriv(`, and
summation constructors before the same completed fraction. Each post-key root
leaf contains the new marker followed by the original `EF 20 id_lo id_hi EF 2D`
marker. The existing fraction record also retains its `+05h` child-selector
byte. The cursor AST carries that byte as `editor_child_selector`, so later
JavaScript mutations reconstruct the live arena rather than replacing it with
the selector implied by a settled tree. All seven translated states match every
record field and the complete cursor-off LCD bitmap. [confirmed]

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

`tools/oracles/mathprint/mathprint-editor-structural-mutation-oracles.json` retains the five
macro and trace hashes, both RAM states, sparse arena bytes, screenshots, and
complete LCD hashes. [confirmed]

`editorInsertStructuralTemplate()` retains the old entry byte before
reconstructing the arena. Across all 17 radical transitions, its cursor AST
matches the decoded post-key tree, reconstruction matches every record field,
and execution matches all 768 LCD bytes. The fraction discriminator has the
same record and LCD parity. Seven additional transitions cover insertion before
an existing fraction marker. Other deeper structural positions and
structural-boundary navigation outside the fraction, integral, summation,
`nDeriv(`, and log-base cases remain open. [confirmed]

### Cursor navigation

Cursor movement is token movement until it reaches a structural boundary. At
that point it becomes tree navigation:

```pseudocode
\begin{algorithm}
\caption{Move the MathPrint cursor}
\begin{algorithmic}
\IF{a packed token exists in the requested direction}
  \STATE move the complete one- or two-byte token across the gap
\ELSIF{the cursor is entering a structural marker}
  \STATE select the first child for \textsc{right}, or the last child for \textsc{left}
\ELSIF{a sibling exists in the requested direction}
  \STATE commit the current child and select the sibling endpoint
\ELSIF{the cursor is inside a structural record}
  \STATE commit the child and return before or after the containing marker
\ELSE
  \STATE leave the root state unchanged
\ENDIF
\end{algorithmic}
\end{algorithm}
```

Ordinary in-leaf navigation uses the page-6 gap movers. **LEFT** reaches
`06:4294–42C7` through `34:42B4` and `00:3B49`; **RIGHT** reaches
`06:42C8–4301` through `34:4193` and `00:367B`. Both paths call
`00:1FE7` so a two-byte native token crosses the gap as one unit. Structural
record markers remain on separate page-34 paths. [confirmed]

`tools/oracles/mathprint/mathprint-editor-navigation-oracles.json` captures `12` with the cursor
at the end, after **LEFT** places it between the digits, and after **RIGHT** returns it
to the end. The middle state splits the logical payload into left byte `31h`
and right byte `32h`; its cursor offset is one. Its active leaf width is 12
pixels, not 18: before existing payload the cursor overlays the following cell
without adding width. At the leaf end, the cursor allocates a six-pixel cell
and the width returns to 18. All three reconstructed record sets and complete
cursor-off LCD bitmaps match their calculator states. [confirmed]

`editorMovePackedTokenCursor()` translates both directions and rejects a
structural boundary rather than applying the ordinary token rule there. After
the decoder emits a cursor inside a numeric run, the following digit begins a
new atom before the two sides recombine around the cursor. [confirmed]

A structural marker occupies six bytes:
`EF type id_lo id_hi EF 2D`. **RIGHT** immediately before the marker selects the
first child at byte offset zero. **LEFT** immediately after the marker selects the
last child at the end of its payload. Both paths store the marker's starting
offset in the containing leaf, set the structural record's one-based child
selector at `+05h`, and increment the controller depth. The **RIGHT** route follows
`34:4193–419B`, `34:41E6–41F5`, and `34:4285–4290`. The **LEFT** route follows
`34:42B4–42BC` and `34:4311–4338`. [confirmed]

The entry routes commit the containing gap leaf before selecting a child. A
leaf can temporarily hold the left-gap byte count at `+11h`. The commit restores
the complete payload length. A summation followed by `X` enters its marker from
the right with `+11h = 6`, then stores `+11h = 7` while the cursor is in the
summation. `editorMoveCursor()` performs the same restoration from the decoded
payload length. [confirmed]

**RIGHT** at a non-final child endpoint selects the next child at byte offset zero
through `34:4193–41D7`. **LEFT** at a non-first child start selects the preceding
child at its payload end through `34:42B4–42EA`. Each route stores the old
child endpoint in that leaf's `+0Fh` word and updates the one-based selector.
Ordinary movement within a child changes only the active gap split; its stored
`+0Fh` word remains unchanged until a structural transition commits the
endpoint. [confirmed]

**RIGHT** at the final child endpoint returns to the containing leaf immediately
after the marker through `34:41DC–4245`. **LEFT** at the first child start returns
immediately before the marker through `34:42ED–430E`. The containing structural
record becomes the controller, and the depth decreases by one. At the root
leaf's outer endpoints, `34:41AE–41DF` and `34:42C5–42CC` return without
changing the arena. [confirmed]

`tools/oracles/mathprint/mathprint-editor-structural-navigation-oracles.json` retains seven
reset-origin traces. Each fraction direction has seven adjacent RAM states.
The integral traces retain 11 **RIGHT** states and ten **LEFT** states. A
depth-two fraction trace retains 11 **RIGHT** states. The summation traces retain
11 **RIGHT** states and ten **LEFT** states. Their 60 key transitions cover entry,
ordinary child movement, sibling selection, nested entry and exit, structural
exit, and root endpoint no-ops. `editorMoveCursor()` reproduces every controller,
active leaf, cursor offset, payload, child list, `+05h`, `+0Fh`, and `+11h`
transition. Its returned decoded arena feeds the next movement directly. All
seven sequences reach every subsequent captured state without replaying a
recorded result. [confirmed]

One additional natural trace walks completed `nDeriv(X,X,1)` and
`logBASE(2,8)` templates in both directions. Its four sequences retain 30 RAM
states and 26 adjacent key transitions. The `nDeriv(` traversal covers its
atomic variable plus ordinary body and evaluation-value children. The
log-base traversal confirms that navigation follows the native base/argument
child order. For these four sequences, `editorMoveCursor()` also matches every
layout word and the reconstructed LCD bitmap at each state. [confirmed]

A second natural trace adds both directions for absolute value, radical,
$e^x$, $10^x$, nth-root, and postfix power. Its 12 sequences retain 66 RAM
states and 54 adjacent key transitions. Together the two trace files cover 96
states and 80 transitions across 16 sequences. Root-level live navigation is
therefore captured for every insertable structural type `0x20`–`0x2A`.
Type `0x2B` matrices are assembled from bracket tokens in the editor rather
than entered as a structural template controller. [confirmed]

One more natural trace walks `[[1]]` in both directions. Its two sequences
retain 14 RAM states and 12 adjacent key transitions, including the endpoint
no-ops. Moving across the five packed tokens relocates the semantic cursor
outside the outer list, inside either list frame, and on both sides of the
element. `editorMoveCursor()` decodes each post-move AST rather than replaying
those shapes. [confirmed]

The depth-two fraction's mirrored **LEFT** trace adds 11 states and ten
transitions. It starts after the outer fraction, enters its atomic denominator,
returns to the outer numerator, enters the inner fraction from the right, walks
both inner children, and exits both controller levels before checking the root
endpoint. [confirmed]

A mixed-controller trace walks a completed fraction inside a radical in both
directions. Its 18 states and 16 transitions enter and exit a one-child radical
and a two-child fraction at depth two, with geometry-first cursor placement at
both marker boundaries. The extra navigation corpus now has 139 states and 118
transitions across 21 sequences. [confirmed]

The reducer decodes each TilEm PNG and compares its black expression pixels
with the translated record renderer. Because the blinking cursor may be gray,
black, or absent, it masks only the cursor-cell rectangles emitted from the
decoded active leaf. All other 96-by-64 pixels must agree. Every state in all
21 sequences passes that independent screenshot comparison as well as
the exact arena comparison. [confirmed]

The cursor cell changes live metrics when it moves within a child. Entering the
`nDeriv(` evaluation value at its end expands that leaf from four to nine
pixels and propagates the five-pixel increase through the structural record and
its ancestors. Log-base applies the analogous propagation and shifts its
argument when the base cell expands. The translated post-move construction
pass reproduces those record updates while leaving the page-6-owned `+0Fh` and
`+11h` gap words intact. [confirmed]

A cursor immediately before a fraction, nth-root, or postfix-power marker
allocates a large or small cursor cell because those structures begin with
geometry rather than a full-size operator cell. Other structural markers let
the cursor overlay their leading operator. For postfix power, the base remains
before the six-byte marker in the parent leaf. The decoded editor AST therefore
keeps a cursor at that boundary inside the power base; placing it after the
completed power would reconstruct the cursor six bytes too far right.
[confirmed]

The integral variable child uses leaf render type `0x01`. Its cursor remains at
byte offset zero. **LEFT** from the root's post-marker position enters that child
at zero rather than at the payload end. A second **LEFT** commits offset zero and
selects the body at its payload end. In the other direction, **RIGHT** from the
variable's offset zero commits its full payload length in `+0Fh` and exits the
integral. The variable therefore has no separate pre-token and post-token
cursor states. [confirmed]

A leaf containing only `EF 1E` is also atomic. The depth-two fraction trace
enters the outer denominator at offset zero. **RIGHT** commits the two-byte
payload in `+0Fh` and exits the outer fraction without exposing a cursor state
after the empty square. This trace supplies the natural witness for
`34:75BB` fallthrough. [confirmed]

The type-`0x29` summation traces combine both atomic forms in one four-child
record. The variable child has type `0x01`; the lower-bound child retains
`EF 1E`; the upper-bound and body children contain ordinary digits. A trailing
root `X` adds ordinary parent-leaf movement before or after the structural
crossing. Both directions visit all four children. [confirmed]

The summation fill trace retains eight adjacent states from template insertion
through structural exit. The new variable child begins as type `0x01` with an
`EF 1E` payload. Inserting `X` reaches the type test at `34:4796`–`34:479B`,
commits the one-byte variable, and calls `34:4181` to select the lower-bound
child automatically. Lower-bound, upper-bound, and body insertion remain in
their current child. The following **RIGHT** commits that child's payload length
to `+11h` and either selects its sibling or exits the summation.
`editorInsertPackedToken()` and `editorMoveCursor()` reproduce all seven
transitions as one composable decoded-arena sequence. The sequence starts from
the decoded arena returned by `editorInsertStructuralTemplate()` for a blank
root rather than from the first recorded summation state. Each reconstructed
state matches the calculator's record fields and cursor-off LCD bitmap.
[confirmed]

### Deletion and structural collapse

Deletion distinguishes ordinary bytes from empty structural children:

```pseudocode
\begin{algorithm}
\caption{Delete at the MathPrint cursor}
\begin{algorithmic}
\IF{the target is an ordinary packed token}
  \STATE remove the complete native token
  \IF{a non-root leaf becomes empty}
    \STATE install the empty-slot token \texttt{EF 1E}
  \ENDIF
\ELSIF{the target is an empty structural child}
  \IF{the record has one child}
    \STATE unwrap that child
  \ELSIF{the type is a fraction or nth root}
    \STATE promote the sibling payload
  \ELSE
    \STATE retain the blank child
  \ENDIF
\ENDIF
\end{algorithmic}
\end{algorithm}
```

The generic transition tests apply the same decoded-arena rules to types
`0x20`–`0x2B`, a six-child matrix, two-byte child tokens, and depth-two nested
markers. The type-`0x01` variable rule is also tested in the integral,
`nDeriv(`, and summation child positions. Live root-level sequence parity now
covers every insertable type `0x20`–`0x2A`; all 16 added directions include
exact layout-word and screenshot parity. One depth-two fraction **RIGHT**
and one **LEFT** traversal are also captured. The two token-built matrix
directions and both radical/fraction directions include the same exact parity.
Matrix deletion, row/column edits beyond the captured one-cell stream, and
other deeper structural combinations remain open. [confirmed]

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

`tools/oracles/mathprint/mathprint-editor-deletion-oracles.json` retains adjacent root and
fraction-numerator deletion states. `editorDeletePackedToken()` produces both
decoded post-key trees exactly, reconstruction matches every record field, and
execution matches both complete cursor-off LCD bitmaps. The finite tests also
delete a two-byte native token as one unit. [confirmed]

**DEL** on a structural child reaches `34:44F4`. `34:47C7` checks that the
active child contains only `EF 1E` and that the cursor precedes that token.
`34:4504–450D` then compares the child count at `0x8DBA` with one. A one-child
record reaches `34:4537`, where `34:47FF` removes the six-byte marker and the
record with its direct child leaf. `34:453A–4544` rebuilds the parent layout
and makes the containing leaf active. [confirmed]

Fraction type `0x20` and nth-root type `0x24` take `34:451F–4534` for either
child. `34:452F` XORs the one-based child selector with `3`, which swaps child
one and child two. The loop copies the sibling's native payload into the
containing leaf before it removes the wrapper. Deleting an empty numerator can
therefore promote a denominator, and deleting an empty nth-root index can
promote its radicand. The reverse directions promote the numerator or index.
An `EF 1E` sibling contributes no bytes. [confirmed]

The other multi-argument types fail the `0x20` and `0x24` comparisons at
`34:4513` and `34:4517`. They fall through `34:451C` to ordinary deletion at
`34:456C`, which leaves the empty-slot token unchanged. Integral `0x22`,
nDeriv `0x23`, log-base `0x28`, and summation `0x29` therefore retain a blank
active child. [confirmed]

Schema 4 of `tools/oracles/mathprint/mathprint-editor-structural-deletion-oracles.json` retains
nine live transitions. They cover both promotion directions for fractions and
nth-roots, a blank radical, a power that retains its `Ans` base, and the
protected integral path. `editorDeleteStructuralTemplate()` mutates the
decoded record graph, then runs the graph decoder at the parent cursor
position. All nine cursor trees, meaningful record fields, and complete
96×64 LCD bitmaps match the calculator. A finite dispatch test applies the
classifier to blank insertion states for every type from `0x20` through
`0x2A`. [confirmed]

When deletion empties a leaf inside another structural record,
`34:454D–455B` checks the new controller type and inserts `EF 1E`. A fraction
deleted from a radical radicand therefore restores a square in the radicand and
leaves the cursor before it. The top-level type-`0x1F` wrapper returns at
`34:4554`, so a deleted top-level template can leave a zero-byte root leaf.
[confirmed]

The ROM leaves `EFh` in physical byte `+0x13` when the resulting active payload
is empty. That byte lies outside the logical payload. Other nested deletion
states, matrix type `0x2B`, and structural-boundary deletion remain open. [confirmed]

`34:759C–75A5` first subtracts six from its record pointer and compares that
source pointer with `editTail`. Only equality reaches `34:789A`. That helper
tests bit 0 of `tblFlags`; when the bit is clear, it forces NZ, and when the bit
is set, it preserves `A` while testing `cxCurApp` against `kYequ` (`49h`). A
zero result therefore requires both the bit and the **Y=** application. Natural
RAM and screenshot captures show the bit set while the inverse-video `=` field
is selected. [confirmed]

### **Y=** selection state

The **Y=** editor stores a one-byte selection-field prefix at `editTail`, then
advances the page-6 record source past it. The first compared source pointer is
therefore `editTail + 1`; later records advance farther through the bounded edit
buffer. The short `X^2` selection trace enters both metric passes with
`editTail = 0xFC9A` and source pointer `0xFC9B`. An overflowing six-power expression
enters 12 times with source deltas 1, 9, 17, 25, 33, and 41 in each of its two
passes. Selecting `=` on an empty expression makes no metric call. These three
captures are recorded in `tools/oracles/mathprint/mathprint-yequ-selection-oracle.json`. Thus a
valid state that makes `34:789A` return Z has already failed the pointer guard,
and `34:75A9` taken is infeasible under this entry invariant. The JavaScript
translation retains the raw early-return path for byte-level routine parity.
[confirmed]

When the **Y=** selection guard is false, `34:75AB` reads the marker type from
`editTail + 1`.
`34:40F9` groups fraction (`0x20`), nth-root (`0x24`), and power (`0x2A`)
markers; `34:75B0` takes its Z branch for this set. `34:75B8` then reads the
nesting counter at `0x8515`, and `34:75BB` distinguishes zero from nonzero
depth. `tools/macros/mathprint-power-boundary-insert.macro` reproduces the
top-level power-marker path. The mixed radical/fraction trace naturally
exercises `34:75B0` fallthrough. Both depth-two fraction directions naturally
exercise `34:75BB` fallthrough at nonzero depth. The **RIGHT** fraction trace
remains the first report witness for the latter. [confirmed]

### Record-oracle coverage

The record-oracle corpus contains 114 captured cases and includes every type
from `0x1F` through `0x2B`. Types `0x20`–`0x2B` have decoded record nodes and
complete accepted-write oracles. The type-`0x1F` case is the transparent
one-child wrapper described below: it has a captured node, child write stream,
and pixel-exact entry screenshot, but it emits no primitive of its own. This
saturates the 13-type record-node domain, not the internal branches of every
handler. [confirmed]

`eqdisp_draw_marker_primitive` has two distinct entry ABIs. Render-table row 0
in `eqdisp_render_handler_table` (`34:6119`) contains
the bytes `43 61`, the pointer `6143h`. `_LdHLind` at `00:0033` executes
the following sequence:

```z80
LD A,(HL)
INC HL
LD H,(HL)
LD L,A
RET
```

Its low-byte load therefore makes a type-`0x1F` table dispatch enter
`eqdisp_draw_marker_primitive` with `A=0x43`. That value follows
the fixed default path to the seven-row bitmap at `34:61BE`; `(IY+44h).3` and
`0x8520` do not affect this ABI. [confirmed]

## Shared marker rendering

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
render type at `0x8DE7`. The following jump to `eqdisp_render_child1`
(`34:636C`) renders child 1 without using `eqdisp_render_handler_table`. A natural matrix-entry capture contains wrapper
ID `6` at `0x9DB7` and child leaf ID `7` at `0x9DF9`. Executing the captured
graph through the JavaScript walker reproduces its 76-by-10-pixel entry image
with zero differences. The wrapper contributes no pixel operation; all 175
accepted writes come from its child program. [confirmed]

The JavaScript record walker therefore keeps the two ROM-proven ABIs separate.
A one-child type-`0x1F` node follows the natural `eqdisp_render_child1`
continuation. A childless node models the independent
`eqdisp_render_handler_table` entry and its row-0
bitmap. No retained natural trace combines `0x8DE7=0x1F` with `34:6105` →
`34:6143`, so the latter remains a decoded table ABI without a natural record
dispatch. [confirmed]

`settledSharedMarkerPrimitive()` translates every conditional at
`34:6143–61BD`. Its finite test enumerates all 256 values of `A`, both states
of `(IY+44h).3`, and all 65,536 values of `0x8520` when `A=0x2B`. Values of
`0x8520` are irrelevant for other `A` values. The resulting 33,554,432-state
projection has 14 path classes and 26 branch outcomes. [confirmed]

For the type-`0x2B` matrix marker, a nonzero high byte at `0x8521` or a low
byte at or above the active bound emits display code `0x7C` and sets
`(IY+32h).2`. The bound is six when `(IY+44h).3` is clear and eight when it is
set. A smaller low byte emits `0xC1` when that flag is set. When it is clear,
the helper emits the five-row bitmap at `34:61C7` and clears `(IY-1).0`.
Retained natural traces do not yet exercise the four matrix-only conditionals
at `34:6178`–`34:618E`. [confirmed]

The object walker calls the post-render tail at `34:61CE` with the current
record type in `A`, the handler's one-based child selector in `E`, and the
structural nesting counter at `0x8515`. Types `0x21`, `0x27`, and `0x2B`
always join `34:79C9` and decrement that counter. Type `0x22` decrements for
child 3 or later; types `0x24` and `0x28` decrement for every child except
child 1; type `0x23` decrements only for child 2; and type `0x29` decrements
only for child 4. Every other type/child state preserves the counter. The
decrement is byte-sized, so zero wraps to `FFh`. [confirmed]

`settledRenderNestingTail()` translates the returned `A`, complete conditional
path, and counter transition. A raw interpreter executes the pinned bytes at
`34:61CE`–`34:6209` and `34:79C9` for every type/child byte pair against four
counter values, then checks every counter byte on one decrementing and one
preserving path. The symbolic model partitions all
$256^3=16{,}777{,}216$ type, child, and counter states into 15 paths. Natural
traces cover every conditional outcome except the type-`0x2B` branch at
`34:61E2`; its behavior is established by the pinned byte interpreter and
finite transition model rather than claimed as a natural witness. [confirmed]

Page `39` layout control remains incomplete. Its class and handler tables, argument
order, row composition, descriptor mapping, and draw paths are decoded. The
browser-side ROM engine now translates the `39:4A74` token/action dispatch and
its `IY+2` exponent-context and `IY+9` fraction-context class adjustments
through `editorTokenDispatch()`. It returns the measured-template handoff at
`39:672E` separately from normal `39:4C27` handler lookup. [confirmed]
## Page 39 argument layout and VAT search

Page `39` maps the current token class to a handler recipe, selects a visible
argument window, and emits its cells. When scrolling needs the neighboring
named operand, saved OP identities feed the alphabetic VAT search rather than
a parser-stream scan. [confirmed]

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

### Alphabetic VAT selection

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
Their restore and writeback operations leave OP1+9 and OP1+10 untouched. The
page-7 entry at `07:50BE` copies all 11 bytes from OP1 to OP3 through
`00:1A0F`. Candidate construction starts by clearing all 11 bytes of OP2 at
`07:51ED`; `07:522E` then copies the byte immediately below the selected VAT
record to OP2+9 at `0x848C`, while OP2+10 remains zero. The full-register
copies through `00:1AE7` and `00:1A4E` return those values in OP3 and OP1.
Failure instead restores both incoming extension bytes from OP3. The
translation and its raw wrapper oracle model this 11-byte behavior while the
saved E7/F2 slots remain nine bytes. [confirmed]

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
`A = 06h` repeats the alphabetic search, while every other value returns with
carry clear. The JavaScript model derives each result from OP1 and a logical
VAT snapshot. It derives the post-search `A` from the selected OP1 type, so a
protected-program entry repeats without an injected return sequence. Nested
and multi-argument states can therefore exercise the search without replaying
an LCD stream. The page `39` control flow and bcall identities are [confirmed].
The page `07` inputs, outputs, and flag behavior are [confirmed].

`editorFindAlphaVat()` translates the selection state over an explicit logical
VAT snapshot. Each snapshot entry contains its nine-byte OP-format identity,
the byte immediately below its record, its VAT type-byte address, and its
data-page byte. `07:50BB` loads `A = 00h`, discarding the caller's
value; `07:5104`–`07:511D` always compare the normalized type class.
[confirmed] `07:5247` maps protected programs to the program
class, complex lists to the list class, type `0x0B` to equation class `0x03`,
and types `0x18`/`0x19` to class zero. [confirmed] The comparator at
`07:5199` subtracts eight name bytes from OPx+8 down to OPx+1. Borrow
propagation makes OPx+1 the most-significant alphabetic byte. The scan retains
the nearest name above or below the incoming OP1, independent of physical VAT
entry order. It returns the selected identity plus the two extension bytes in
OP1 and OP3, its VAT pointer in `HL`, and carry at an alphabetic endpoint.
[confirmed]

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
length two. A failed search restores the complete original, unpadded OP1 from
OP3.
[confirmed]

Success returns `A = 00h`, Z set, and carry clear. Failure restores all 11
incoming bytes to OP1/OP3 and returns `A = FEh`, Z clear, and carry set.
[confirmed]

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

## From live editor state to settled drawing

### Trace provenance and scope

Two reset-origin TLMT v2 traces use the pinned ROM SHA-256
`7d9a7d96d89fc552ebee6afdbdd011fdc6047be9c16d308245dff07eb1f7bd6d`.
The raw traces remain outside the repository because they are 162 MB and 202 MB.
`tools/oracles/mathprint/mathprint-trace-report.json` records their hashes, emulator provenance,
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

### Settled render dispatch

For either a live-editor or settled redraw, page `34` walks the arena
recursively. The live path first substitutes the active gap payload through
`eqdisp_substitute_active_leaf`. A leaf then executes its token-and-marker
payload; a structural
record delegates placement to the handler for its type:

```pseudocode
\begin{algorithm}
\caption{Render an arena record}
\begin{algorithmic}
\STATE $record \gets \operatorname{ResolveRecordId}(id)$
\IF{$record.type < \mathtt{0x1F}$}
  \STATE $\operatorname{ExecuteLeafProgram}(record.payload, origin, depth)$
\ELSE
  \STATE $handler \gets \operatorname{StructuralHandler}(record.type)$
  \STATE $\operatorname{RenderPlacedChildrenAndPrimitives}(handler, record, origin, depth)$
\ENDIF
\end{algorithmic}
\end{algorithm}
```

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

For the nested scenario, `tools/ti84re/mathprint/analyze_draw_trace.py` attributes all
391 visible-changing writes after the final key. The nearest page `34` frames
are `34:5FE7` → `ram:34E9` (158 writes), `34:6CA8` → `ram:3CE1` (96),
`34:5DA2` → `ram:3573` (78), `34:5EA3` → `ram:3567` (24), and `34:5DBA` →
`ram:3579` (10). The remaining 25 writes precede the page `34` object traversal
and come from the large-font path. The fixed-page stubs dispatch to page `04`
line and point routines and page `01:6297` small-font output. [confirmed]

### Point and line primitives

A structural handler emits local points or axis-aligned lines. The shared
drawing backend then applies four stages in order:

1. Add the word-sized logical record origin.
2. Subtract the horizontal or vertical viewport clip.
3. Add the byte-sized physical screen origin and reject out-of-bounds points.
4. Route each accepted point to the LCD, `plotSScreen`, or
   `appBackUpScreen` according to the destination flags.

The split between logical and physical origins is explicit in
`EqDispViewportState` (`0x8DFA`): [confirmed]

```c
#pragma pack(push, 1)
typedef struct {
    uint8_t physical_x;
    uint8_t physical_y;
    uint8_t right_bound;
    uint8_t bottom_bound;
    uint16_t logical_x;
    uint16_t logical_y;
    uint16_t horizontal_clip;
    uint16_t vertical_clip;
} EqDispViewportState;
#pragma pack(pop)
```

The point wrapper at `34:5E85` clips each object coordinate through `34:5DD1`
and `34:5DEF`. Its closed tail at `34:5E98`–`34:5EA6` passes `B=x`,
`C=63-y`, and `D=1` to `_PointOn` at `04:4155`. Dynamic samples include
`(x,y)=(3,0)` → `BC=033Fh` and `(32,20)` → `BC=202Bh`. [confirmed]

`_IPoint` first supplies drawing-hook command `0` at `04:4158`. An inactive
hook preserves Z from the bit test and takes `04:4161` into the local point
path. An active hook can return Z to request the same continuation; NZ restores
the caller's AF and returns without a local write. The translated dispatcher
keeps the hook body as an explicit external boundary. [confirmed]

The local preprocessor then tests `sGrFlags.g_style_active`. Retained MathPrint
calls have both the drawing hook and this style bit clear, so `04:4177` jumps
directly to the coordinate path. That path adds the bytes at
`ram:8DA1` and `ram:8DA2` to `B` and `C`, with byte wraparound, before checking
the display bounds. `apiFlg4.fullScrnDraw` selects `04:4306`, which admits
$x$ bytes below `ram:8DA4` and $y$ bytes below 64. Clearing the flag selects
`04:42EC`, which decrements the width bound and also rejects row zero. Both
flag states occur in retained MathPrint traces. [confirmed]

The same translation covers the shared graph-style path rather than assuming
that style state is always inactive. Style `1` at `04:4196` emits the current
point and one to three neighboring attempts chosen from the unsigned
current/previous coordinate relations. It stores the current `B:C` at
`ram:9315` for the next call. Styles `2` and `3` enter `04:40AD`; the phase at
`ram:9668`, step at `ram:966C`, style parity, and `(IY+1Eh).7` select an aligned
ascending or descending point sweep. `04:6F84`–`04:6FAC` initializes the phase
modulo four, while the graph update path keeps the step in `1`–`3`. Styles
`0` and `4`–`FFh` emit only the original point. [confirmed]

`settledPage4PointPipeline()` processes every accepted expanded point in ROM
order through the existing LCD/`plotSScreen`/`appBackUpScreen` byte router.
This ordering preserves repeated visits to one byte instead of evaluating the
expanded points independently. A pinned-byte interpreter agrees with the
JavaScript preprocessor across 169,443 states: every input coordinate under
both bounds helpers, offset and width boundary cases, all thick-point relation
classes, every style-dispatch byte, and valid shaded phase/step samples. The
symbolic report separately partitions all 512 style-dispatch states, all
33,554,432 effective-coordinate bounds states, all 4,294,967,296 thick-point
coordinate relations, and all 3,145,728 graph-initialized shaded states at the
64-row limit. Arbitrary drawing-hook body behavior remains external.
[confirmed]

`04:42B5`–`04:42E3` converts the graph coordinate into the point mask, LCD
commands, and buffer offset. It selects `80h >> (x & 7)`, uses `x >> 3`
as the byte column, and computes `3 * ((4 * display_row) & FFh) + byte_column`.
The row multiplication keeps its intermediate in one byte. Rows `40h`–`7Fh`
therefore alias rows `00h`–`3Fh` before the column is added. `_PointOn` fixes
`D=1`, so `04:424D`–`04:4254` ORs that mask into the current byte. MathPrint's
wrapper clips to the 96×64 display before this entry. [confirmed]

The offset addresses `plotSScreen` at `0x9340` and `appBackUpScreen` at
`0x9872`. `04:424C`–`04:42B4` maps `D=0`, `1`, `2`, and `3` to clear, set,
XOR, and test. Test returns the masked bit without writing. The other modes
route the resulting byte according to `(IY+3Ch)` and `plotFlags.1` at
`(IY+02h)`. Bit 3 selects `appBackUpScreen` and bypasses LCD I/O. Otherwise,
bit 0 selects the same direct-RAM route through `plotSScreen`. With both bits
clear, the routine reads and writes the LCD. `plotFlags.1` chooses the LCD byte
as the source and preserves `plotSScreen`; clearing it selects and rewrites the
RAM byte. Bit 2 mirrors the result to `appBackUpScreen`. [confirmed]

Retained MathPrint traces take the LCD route: `(IY+3Ch)` bits 3, 2, and 0 are
clear, while `plotFlags.1` is set. The translated renderer therefore reads the
current LCD byte, applies the point mode, and emits the accepted controller
write without modifying either RAM buffer. A raw interpreter checks all four
modes, every source byte, all eight masks, every `(IY+3Ch)` byte, and both
values of `plotFlags.1`. This covers 524,288 routing transitions in addition to
the 8,192 isolated mode/mask transitions. [confirmed]

`04:426B` contains a controller-dependent workaround. When the hardware check
returns NZ, byte column 5 and rows before command `B7h` force result bit 0 on
the LCD write. The state transition exposes that condition explicitly. It does
not apply the modified LCD byte to either RAM destination. [confirmed]

The JavaScript translation matches a raw interpreter of the pinned helper
bytes for all 65,536 input-coordinate pairs. A second exhaustive comparison
covers every previous byte for each visible coordinate: 1,572,864 point-on
transitions. The wider diagnostic canvas used for overflow inspection can have
coordinates above `FFh`; those pixels cannot enter the page-4 byte ABI and are
kept separate from the physical LCD claim. [confirmed]

The line wrappers share `eqdispViewport`. `eqdispViewport.physical_x` is the
screen $x$ origin, while `eqdispViewport.logical_x` is the record $x$ origin.
`eqdispViewport.physical_y` and `eqdispViewport.logical_y` are the corresponding
$y$ origins. Keeping those pairs separate matters in
shifted editor modes even though all four values are zero on the normal home
entry line. [confirmed]

`34:5D96` passes a clipped vertical segment to `04:431D`;
`eqdisp_draw_hline_clipped` (`34:5DA6`) swaps the
axes and passes a clipped horizontal segment to `04:4382`. The nested trace's
fraction rule enters `34:5DA6` with object coordinates `x=1`–`5`, `y=6` and
origins `x=16`, `y=5`. Page `04` receives endpoints `(17,52)` and `(21,52)`.
[confirmed]

The callers supply ordered endpoints. The wrappers treat the two varying
coordinates asymmetrically. An underflow of the first coordinate against the
logical clip clamps to zero. A first coordinate at or beyond the exclusive
screen bound returns without drawing. The second coordinate instead returns
on underflow and clamps at `bound-1` on overflow. `04:4379` performs the
exclusive-bound test, while `04:43C0` selects the smaller ending coordinate.
The JavaScript transition keeps the word-sized logical origins and clips
separate from the byte-sized physical origins. [confirmed]

`_DarkLine` at `04:4025` fixes `H=1` before entering `_ILine` at `04:4029`.
`04:4042`–`04:4069` computes the absolute byte deltas, direction bits, major
axis, doubled minor increment, and signed error. `04:4078` calls `_IPoint` at
`04:4157` before each step, so both endpoints produce writes. The major delta
is incremented as a byte; a delta of `FFh` therefore produces 256 point
visits. [confirmed]

A raw interpreter of the pinned `_DarkLine` bytes checks all 131,072 ordered
endpoint pairs for horizontal and vertical lines. It also checks all 65,536
nonnegative delta pairs, which covers every major/minor ratio and signed-error
sequence. Separate reverse-direction cases cover the direction branches.
Physical MathPrint lines now compose this stepper with the translated point
state transition. A hook-handled point remains delegated to the external hook
body and produces no inferred local LCD write.
[confirmed]

### Word-sized geometry and clipping

The structural handlers retain coordinates and dimensions as 16-bit words.
For example, `34:62B4`–`34:62C3` reads a radical child's width word, increments
`DE` three times, and passes the resulting word endpoint to `34:5DA6`.
`34:620A`–`34:622C` performs the corresponding word comparison for a fraction.
The translated renderer therefore accepts widths beyond 255 and wraps additions
at 16 bits before viewport clipping. A radical with record width 258 reaches a
clipped vinculum from $x=-167$ through $x=87$ instead of rejecting the record
as byte-sized geometry. [confirmed]

### Structural render handlers

The dispatcher is easiest to read as a vocabulary of visual constructs. The
paragraphs below retain the coordinate and trace details for each row.

| Type | Construct | Handler | Distinctive ordered output |
|------|-----------|---------|----------------------------|
| `0x20` | Stacked fraction | `34:620A` | Numerator, denominator, then a rule sized from the wider child. |
| `0x21` | Absolute value | `34:6347` | Two vertical bars, then child 1. |
| `0x22` | Integral | `34:622F` | Inclusive stem and four hook points; child placement comes from the record. |
| `0x23` | `nDeriv(` | `eqdisp_render_handler_table` | Derivative fraction, body, variable, evaluation bar, then repeated variable and value. |
| `0x24` | nth root | `34:6315` | Index, root hook and stem, radicand, then vinculum. |
| `0x25` / `0x26` | $e^x$ / $10^x$ | `34:6381` | Fixed glyph, then exponent child. |
| `0x27` | Square root | `34:62A1` | Root hook and stem, radicand, then vinculum. |
| `0x28` | `logBASE(` | `34:63B2` | Prefix, base, opening shape, argument, then closing shape. |
| `0x29` | Summation | `34:6504` | Sigma/equals forms, children 1–3, then delimited child 4. |
| `0x2A` | Postfix power wrapper | `34:6375` | Recursively renders child 1; emits no primitive itself. |
| `0x2B` | Matrix | `34:65AA` | Left bracket, row-major children, then right bracket. |

Render-record type `0x22` dispatches through `34:6105` and
`eqdisp_render_handler_table` to `34:622F`. The word at record offset `+7` is the integral-sign
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
emits the ten-byte root-hook bitmap through `eqdisp_draw_radical_hook`
(`34:62D0`), draws the vertical stem,
selects child 1, and reads that child's word at offset `+7`. It then draws the
inclusive vinculum from `(2,0)` through `(w+3,0)` and renders child 1 through
`eqdisp_render_leaf_program`. The cursor-free history redraw for `sqrt(X^2+1)` has height 8 and a
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

The remaining settled render types map to calculator constructs through
`eqdisp_source_type_table` and post-**ENTER** traces. Type `0x23` renders
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

### Matrix layout

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
type-`0x00` leaf program at `eqdisp_render_leaf_program`. The program executor consumes its payload
in order and invokes embedded structural records against the same pen and depth
state. Row 0 uses the bitmap bytes at `34:61BE`, as fixed by the table-load ABI;
the captured type-`0x1F` wrapper instead uses the direct-child ABI above. The
`nDeriv(` handler renders child 1 again at `34:64B3`, then
places display code `0x3D` after that child's `+7` width. [confirmed]

### Recovering semantic trees from records

A leaf is both text and a small program. Ordinary native tokens expand to
display codes; embedded markers invoke structural records by ID without
discarding the text on either side:

```pseudocode
\begin{algorithm}
\caption{Execute a leaf record program}
\begin{algorithmic}
\WHILE{$pc < payloadEnd$}
  \IF{$pc$ names an embedded structural record}
    \STATE $\operatorname{RenderRecord}(\operatorname{ResolveRecordId}(marker.id), pen, depth)$
    \STATE advance past the marker
  \ELSIF{$pc$ is an embedded-object separator}
    \STATE advance past the separator
  \ELSE
    \STATE $(token, pc) \gets \operatorname{DecodeNativeToken}(pc)$
    \FOR{each $displayCode$ in $\operatorname{KeyToString}(token)$}
      \STATE $\operatorname{EmitGlyph}(displayCode, pen, depth)$
    \ENDFOR
  \ENDIF
\ENDWHILE
\end{algorithmic}
\end{algorithm}
```

The record graph is a layout program. The semantic AST is a second view
decoded from ordered children, balanced native delimiters, and embedded-record
markers. The live-editor path substitutes the active gap payload before this
decode. Neither view is inferred from LCD pixels or screenshots. [confirmed]

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
first `eqdisp_render_leaf_program` entry at the shallowest Z80 stack depth
after the final key press
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
consumed by `eqdisp_render_leaf_program`. The browser-side ROM engine exposes the same decoder for
its generated AST view as `settledAst`. The live-editor wrapper applies this
decoder after `eqdisp_substitute_active_leaf` substitutes the active gap
payload, then inserts the
cursor at the byte boundary selected by `editCursor`. [confirmed]

A structurally populated live matrix entry demonstrates why leaf decoding
cannot treat every payload as a flat token sequence. Before evaluation, wrapper
ID `6` points to a leaf
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

### Glyph selection and hooks

The ordinary-token path resolves payload bytes through `smallfont_glyph_ptr`
at `01:6702`. A zero lead selects the word table at `01:4252`. The two-byte
leads `5Ch`, `5Dh`, `5Eh`, `60h`–`63h`, `7Eh`, `AAh`, `BBh`, and `EFh` select
tables at `01:4452`–`01:47E8`. The `5Eh` second byte selects one of four banks.
The `BBh` path clamps indices `F6h`–`FFh` to `F6h`. [confirmed]

The raw `D:E` selector accepts more states than the native token grammar.
Leads `01h`–`5Ch` alias the `5Ch` table. Both `5Eh` and `5Fh` test index bits
4, 5, and 6 in that order, clear the first selected bit, and otherwise clear
bit 7. Leads `64h`–`7Dh` and `7Fh`–`BAh` alias the `AAh` table. Leads `BCh`–`FFh`
alias the `EFh` table. `_IsA2ByteTok` prevents these extra aliases during
ordinary token decoding. [confirmed]

`01:6765` inherits Z from the preceding `CP BBh`; `LD A,L` does not change it.
That `JR NZ` therefore falls through under the `01:6702` entry ABI. The
`CP 13h` clamp at `01:6774`–`01:6778` has no other predecessor and is
unreachable from this entry. A pinned byte interpreter matches the JavaScript
table, normalized index, pointer-word address, and complete branch sequence for
all 65,536 `D:E` pairs. [confirmed]

`01:6788` skips the token hook when `(IY+35h).0` is clear. When it is set,
`01:7C53` classifies the Catalog2 hook header and version before the token-hook
call. An invalid header returns C and Z, an older version returns C and NZ, the
exact version returns NC and Z, and a newer version returns NC and NZ. Only the
invalid-header class reaches `01:67AC`: offsets through `0546h` retain `BC=0`
and the offset in `DE`, while larger offsets pass the offset in `BC` and
`000Ch` in `DE`. [confirmed]

The page-3B wrapper at `3B:7B8D` either enters the installed hook or clears
`(IY+35h).0` and returns to the ROM string. The finite model covers both flag
values, four Catalog2 classes, all 65,536 offset words, and both wrapper
outcomes. The installed hook body and any pointer or string that it returns
remain external. [confirmed]

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
96×64 LCD bitmap as replaying its captured `eqdisp_render_leaf_program`
interval. `X^Ans` verifies
the variable-width small-font spelling. `sin(sqrt(X))` verifies a counted token
spelling before a structural child and the compound shapes around its taller
metrics. The structural record stores the containing leaf's accumulated
horizontal anchor at `+0x0D`. [confirmed]

Five reset-origin traces cover `L1`, `[A]`, `Y1`, `Str1`, and `X^L1`. Their
generated record graphs match every field after normalizing record IDs. Their
accepted-write streams contain 21, 35, 21, 42, and 22 writes. The generated
stream and captured outer `eqdisp_render_leaf_program` interval have the same
byte-column, row,
and value for every write. Replaying either stream produces the same 96×64 LCD
bitmap. `X^L1` verifies two-byte spelling and width in the small-font exponent
path. [confirmed]

The translated renderer then maps the ordered operations through the ROM font
bitmaps, page-4 point and line behavior, `_VPutMap`, the page-7 large-glyph
path, and LCD byte packing. Six settled programs reproduce every accepted LCD
data write through the outer `eqdisp_render_leaf_program` return: absolute value (49 writes), nth
root (69), radical (82), summation (66), `nDeriv(` (96), and a nested
integral/fraction (114). This comparison includes accepted writes whose value
does not change the displayed byte. [confirmed]

### Compositional metrics

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

`34:6C37`–`34:6CAB` prepares two page-1 driver states. A root glyph uses the
seven-row record built by `07:45B6`. A raised glyph enters `01:6297` with a
one-row source skip and a five-row count, so `01:6354`–`01:6374` advances past
the first small-font padding row. The selected count also omits the trailing
padding row. Vertical viewport clipping changes the skip and count before the
page-1 call. [confirmed]

`34:6C4D` loads the width byte from the selected font record. When
`fontFlags.2` is clear, `34:6CBC` adds three columns for display codes `28h`
and `29h`, and two for `7Bh` and `7Dh`. Other codes retain the record width.
The addition at `34:6C5A` is byte-sized and can wrap. The translated metric and
draw paths use this result for delimiter cells instead of a separate fixed
width. Root calls set `fontFlags.2` and retain the six-column large-font cell.
Raised parentheses begin with width three and raised braces with width four;
the correction expands both families to six columns. A pinned-byte interpreter
covers both flag values and every display-code and width-byte pair. [confirmed]

The two states use different right-edge comparisons. The root state compares
the endpoint with `0x61` at `01:630A`, while the raised state compares it with
`0x60` at `01:630E`. `CCF` followed by `JP C` rejects endpoints at or above the
selected limit. A root six-pixel glyph beginning at `x=90` therefore draws
through pixel 95. A raised four-pixel glyph beginning at `x=92` is rejected as
a unit. Pinned-byte differential tests cover all 3,584 pen-byte, width, and
mode states plus all 112 width, bit-offset, and mode row states. [confirmed]

`01:6360`–`01:6378` computes $8-o-w$, where $o$ is the LCD bit offset and
$w$ is the glyph width. A nonnegative result selects the one-byte path. Its
`DJNZ` entry arrangement rotates the screen byte by the remaining-space count,
calls `01:6431`, and reverses the rotation. A negative result selects the
two-byte path, negates the value to obtain the overflow count, and circularly
rotates the two-byte screen window. [confirmed]

The width-mask table at `01:6446` contains `FE FC F8 F0 E0 C0 80`. For an
aligned screen byte $s$, mask $m$, and glyph row $g$, `01:6431`–`01:6445`
computes $(s \mathbin{\\&} m) \mathbin{\mathtt{xor}} g$ for ordinary text.
When `textFlags.3` is set, it computes
$((\mathord{\sim}m) \mathbin{\vert} s) \mathbin{\mathtt{xor}} g$ instead.
The translated composition matches a pinned-byte interpreter for all 917,504
screen-byte, width, glyph-row, and inverse-flag inputs. An independent row test
covers 7,340,032 screen-window, offset, width, and inverse states, including
both sides of every LCD byte boundary. [confirmed]

### Absolute values, powers, and roots

The absolute-value constructor translates a closed slice of the earlier record
pass. `eqdisp_lookup_render_type` maps source token `00B2h` through
`eqdisp_source_type_table` to
render type `0x21`. The translated `34:4900`, `34:7393`, and `34:7609` paths
construct the containing leaf, the absolute-value record, its child leaf, and
their settled metrics. Fresh reset-origin traces for `abs(2)`, `abs(X/2)`, and
`abs(X+12)` match the generated record fields and every accepted LCD data write.
The trace streams are comparison oracles and are not constructor inputs.
[confirmed]

The compositional constructor translates the type-`0x2A` power and type-`0x27`
radical paths. `eqdisp_lookup_render_type` maps source token `00BCh` through
`eqdisp_source_type_table` to render
type `0x27`; the containing leaf embeds the structural ID and constructs the
radicand as child 1. Its settled height, width, and baseline derive from the
child metrics. Raised radicals select the final five rows of the root-hook
bitmap at `34:62D0`, while outer radicals use all seven rows. [confirmed]

`eqdisp_lookup_render_type` maps source token `00F0h` through
`eqdisp_source_type_table` to render type `0x2A`.
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

### Fixed-base exponentials and log base

The type-`0x25` and type-`0x26` constructors map source tokens `00BFh` and
`00C1h` through `eqdisp_source_type_table`. Both allocate one exponent child. The child begins at
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

The type-`0x28` constructor maps source token `EF34h` through
`eqdisp_source_type_table` and
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
the `2,1` child order in its `eqdisp_child_scan_table` row and leaves this field at `1`.
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

### Nth roots and fractions

The type-`0x24` constructor maps source token `00F1h` through
`eqdisp_source_type_table`, then
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
through `eqdisp_source_type_table`. It renders both children one depth below the containing leaf.
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

`eqdisp_allocate_record` allocates structural records in a fraction numerator before it
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
`eqdisp_render_leaf_program` return. [confirmed]

Integral, summation, and `nDeriv(` records in a fraction numerator follow the
same hoisting rule. `eqdisp_allocate_record` allocates the multi-argument record and reserves
its child leaves before it allocates the enclosing type-`0x20` fraction. The
nested structural record stores `0x10` at `+0x13`. Raised integral layout uses
a 10-pixel body-to-variable gap; the outer layout uses 12 pixels. In a raised
`nDeriv(X^2,X,...)` numerator, the body leaf stores `0x58` before the
type-`0x2A` marker, and the power record stores `4` at `+0x0D`. [confirmed]

Six reset-origin traces cover integral, summation, and `nDeriv(` numerators,
each with an ordinary body and a powered body. Before parity is accepted, the
trace analyzer must decode each settled graph to the asserted expression. The
JavaScript constructor then matches every record field and allocation ID, plus
every accepted LCD data write through the outer `eqdisp_render_leaf_program`
return. [confirmed]

### Integrals, summations, and derivatives

The type-`0x22` constructor maps integral source token `0024h` through
`eqdisp_source_type_table`. `eqdisp_allocate_record` allocates the integral
record, then reserves all four child
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
`eqdisp_source_type_table`. `eqdisp_allocate_record` allocates the summation
record, then reserves child leaves
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

The type-`0x23` constructor maps source token `0025h` through
`eqdisp_source_type_table`. `eqdisp_allocate_record` allocates the `nDeriv(`
record, then reserves child leaves for the
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

### Final clipping and the run indicator

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

Each dispatch also captures `eqdispViewport.logical_x` and
`eqdispViewport.logical_y`.
Nested fraction `1/2` reaches `34:5DA6` with the local rule `(1,6)`–`(5,6)`
and origin `(16,5)`. Page 4 therefore receives the translated endpoints
`(17,52)` and `(21,52)`. [confirmed]

### Record header recap

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
hits. `tools/tests/trace/test_hardware_trace.py` covers this distinction. [confirmed]

## Page 39 cell encoding

`eqdisp_emit_glyph` (`39:4E8E`) interprets each packed `D:E` cell as one of
four output classes:

| Cell class | Meaning | Result |
|------------|---------|--------|
| `D = 1Fh` | Cursor marker | Update cursor state without drawing a glyph. |
| `D = 82h` | Indexed string or title | Emit the selected string. |
| Counted-token case | `39:6B66` to `_KeyToString` (`45CAh`, implemented at `01:6D10`) | Emit each display code from the counted string. |
| Direct-glyph case | Mapper at `39:4F1A` | Map the packed cell to one large-font code. |

The direct mapper recognizes three ranges: `FC3C`–`FC40` becomes
`E - 3Ch + 5`, `FE7D`–`FE81` becomes `E - 7Dh`, and cells with `E = 42h` and
`D < 0Ah` become glyph `D`. `00C8` therefore draws the literal name `fnInt(`,
not one glyph. The full decode is in
`tools/notes/cell-glyph-spec.md` and
`tools/notes/token-name-spec.md`; the placement geometry
(`683D`, `6B1C`, `5167`/`5949`, pen conversion) is in
`tools/notes/geometry-spec.md`. [confirmed]

The JavaScript translation of `39:4F1A` preserves the returned accumulator,
carry flag, and every conditional outcome through `39:4F43`. The handler-cell
classifier consumes that translation rather than a separate mapping table. A
pinned-byte interpreter compares all 65,536 `D:E` inputs. They reduce to nine
complete paths and 16 branch outcomes. [confirmed]
