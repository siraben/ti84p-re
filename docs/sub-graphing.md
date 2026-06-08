# Graphing

*TI-84 Plus OS 2.55MP — feature deep dive.*

What a college student touches when they press **Y=**, **WINDOW**, **GRAPH**, **TRACE**,
or run a **DRAW** menu command. This traces the path real-coordinate → screen pixel →
`plotSScreen` → LCD, plus the window variables, Y= equation storage, and DRAW primitives.

Address form is `page:addr` (flash page hex : logical offset, routines run mapped at
`0x4000`). Confidence: [confirmed] = read the code/data directly, or cross-checked
against equate/convention; [standard] = matches documented TI behavior but not
byte-verified here; [hypothesis] = inferred, not yet verified.

---

## 1. Window variables (RAM) [confirmed addresses, from ti83plus.inc + code refs]

All graph window state lives in a contiguous block of 9-byte `TIFloat`s starting at `0x8F50`.
These are the values the WINDOW editor writes and the grapher reads.

| Addr | Name | Meaning |
|------|------|---------|
| `0x8F50` | `Xmin` | left edge real X |
| `0x8F59` | `Xmax` | right edge real X |
| `0x8F62` | `Xscl` | X tick spacing |
| `0x8F6B` | `Ymin` | bottom edge real Y |
| `0x8F74` | `Ymax` | top edge real Y |
| `0x8F7D` | `Yscl` | Y tick spacing |
| `0x8F86` | `ThetaMin` / `0x8F8F` `ThetaMax` / `0x8F98` `ThetaStep` | polar/parametric range |
| `0x900D` | `XresO` | Xres (pixel step between plotted columns) |
| `0x9151` | `Xres_int` | integer copy of Xres |
| `0x9152` | `deltaX` | `(Xmax−Xmin)/94` — real width of one pixel column |
| `0x915B` | `deltaY` | `(Ymax−Ymin)/62` — real height of one pixel row |
| `0x9164` | `shortX` | scratch/divisor float for the X transform (per-pixel ΔX) |
| `0x916D` | `shortY` | scratch/divisor float for the Y transform (per-pixel ΔY) |
| `0x913F` | `XFact` / `0x9148` `YFact` | ZOOM IN/OUT factors |

There is a second "u" copy block at `0x8E7E` (`uXmin`…`uXres` at `0x8F3B`) — the
uVar window set used in the alternate (split/table) graph context, and a working/temp
float pair around `0x8E6A`/`0x8E73` used by the transform code. [confirmed]

`deltaX`/`deltaY` are derived from the window when the graph is set up and feed both the
forward (real→pixel) and the circle/draw routines. The LCD is `96×64`, but the graph area
is 95 columns wide (0..94) and 63 tall (0..62), hence the /94 and /62. [standard]

---

## 2. Coordinate ↔ pixel transforms

### Forward: real coordinate → pixel index

`_XftoI` (`37:41EB`) and `_YftoI` (`37:41DF`) convert an OP1 real coordinate to a
pixel index. Both are thin shims around the shared engine at `37:41F2`: [confirmed]

```
_XftoI (37:41EB):  BC = 0x8E6A (X working float),  HL = shortX (0x9164),  SCF  → 41F2
_YftoI (37:41DF):  BC = Ymin   (0x8F6B),            HL = shortY (0x916D),  OR A → 41F2; INC A
```

Shared engine `37:41F2` computes $\mathrm{pixel}=\dfrac{\mathrm{value}-\mathrm{min}}{\mathrm{pixelDelta}}$:
- `RST 20h` pushes/loads OP1 (the input value),
- `CALL 228F` moves the `min` operand in and subtracts it (`value − min`),
- `CALL 2385` divides by the per-pixel delta (`shortX`/`shortY`),
- the X path additionally adds the `0x8E73` X-origin term, the Y path negates so that
  larger Y maps to a *smaller* row (screen Y grows downward),
- `CALL 4229` clamps/handles the float→integer exponent (reads `OP1.exp` at `0x8479`,
  bias `0x7F`) and rounds to an integer pixel; out-of-range loads ±large sentinel.
`_YftoI` returns pixel row +1 (`INC A`) so callers get a 1-based / inverted row. [confirmed]

So a student's function value `y` at sample `x` becomes a `(col,row)` pair via two
subtract-then-divide float ops against the window. This is the heart of plotting and TRACE
coordinate readout.

### Inverse: pixel index → real coordinate

`_SetXXOP1` (`33:5F7E`) and `_SetXXOP2` (`33:5F83`) take an integer pixel value in A
and build a real `TIFloat` in OP1 / OP2 (`0x8478` / `0x8483`). [confirmed]
- `CALL 1BA7` zeroes the destination mantissa,
- `CALL 5F6A` converts the binary value to packed BCD by repeated `ADD A,0x16 / DAA`
  (binary→decimal nibble accumulation), looping A times,
- the exponent byte is set so OP1 holds the integer; `_SetXXXXOP2` (`33:5F9E`) is the
  4-digit (up to 9999) variant for larger pixel/coordinate counts.

These are used to turn a pixel column/row (e.g. under the TRACE cursor) back into the real
X/Y shown at the bottom of the screen, and by DRAW commands that take pixel arguments.

---

## 3. The graph buffer `plotSScreen` and pixel addressing

- `plotSScreen` = `0x9340`, 768 bytes = 96×64/8. Monochrome, 1 bit/pixel, 12 bytes per
  scanline (8 pixels per byte). This is the back buffer everything draws into. [confirmed]
- `saveSScreen` = `0x86EC`, 768 bytes — a saved copy (e.g. for redrawing the graph after
  a menu covers it). [confirmed]

`_GrBufClr` (`04:6071`): clears the whole 0x300-byte buffer to 0 (a
`LD (HL),0` + 0x2FF-byte propagate copy). [confirmed]

`_IOffset` (`04:42B5`) computes the LCD controller address bytes for a pixel (inputs `B`=x, `C`=y):
```
(0x844F) = (x >> 3) | 0x20     ; LCD "set row page" command — the rotated TI panel pages by X
(0x8451) = (0x3F - y) | 0x80   ; LCD "set column" command (Y, mirrored)
returns (table_42E4)[x & 7]    ; the 1-of-8 bit mask within the byte (bit = x mod 8)
```
This is the bridge from a `(x,y)` pixel to a byte+bit in the buffer and the matching LCD
command bytes. [confirmed]

`_IPoint` (`04:4157`): set/clear/test one pixel in `plotSScreen`. Honors the current
pen mode / plot style: reads style at `(IY+0x14)` and a style selector at `0x9775`
(`0x9775` = 1 selects the "thick/line connect" branch that draws an extra adjacent
pixel; 1..3 select dotted/animated styles), clips against the X-offset (`XOffset`) and the
buffer bounds (`_IBounds`), then OR/AND/XORs the mask from `_IOffset`. `_PointOn`
(`04:4155`) is the plain set-pixel entry. [confirmed]

`_PixelTest` (`04:79E7`): the `pxl-Test(` command — validates the row/col against the
current graph dimensions `lcdTallP` (`0x8DA3`) and `pixWide_m_1` (`0x8DA5`) — 63 and 95 on a
full screen, smaller when split — maps the split-screen offset, and returns whether that buffer
pixel is on. `_ErrDomain` on out-of-range. [confirmed]

---

## 4. Drawing primitives (page 0x04 / 0x33)

### Lines

`_ILine` (`04:4029`) — integer pixel line via Bresenham. [confirmed]
It computes `dx=|x2−x1|`, `dy=|y2−y1|`, picks the major axis, sets the error term
`(dy−dx)*2`/`dy*2`, then loops `_IPoint` for each step, advancing the minor axis when the
error crosses zero. `graph_chk_flag20` (`04:4316`) is the step-along-major-axis helper. The endpoint and
draw-mode (set/clear/xor) are passed in. `_DarkLine` (`04:4025`) is `_ILine` with
the "draw/dark" mode forced. [confirmed]

`_CLine`/`_CLineS` (`33:6028`/`33:6034`) and `_UCLineS` (`33:6010`) — coordinate
line: take real-coordinate endpoints, run them through the X/Y transforms (the SetXX/ftoI
path), then call the integer line. The `S` variants take an explicit style/mode byte; the
mode bit comes from `(IY+0x35) & 0x80` (`hookflags3` bit 7, the drawing-hook-active flag —
not a split-screen flag). These back the `Line(`
DRAW command at the math layer. [confirmed]

### Circle

`_GrphCirc` (`33:758D`) — draws a circle in real coordinates. [confirmed]
Allocates a 0x5A-byte FPS scratch frame (`EQS`), snapshots the working float and the window
(`Xmin`, `Ymin`, `deltaX`), zeroes accumulators, seeds the X/Y center and the radius-stepped
parametric state, then iterates plotting points via the integer line/point primitives
(cross-page into the page-3B `_DrawCirc2` plotter at `3B:7171`). It accounts for the X/Y
pixel-aspect via `deltaX`/`deltaY` so a `Circle(` looks round only after a ZSquare. [confirmed]
`_CircCmd` (`33:74CE`) is the parser-facing `Circle(` command wrapper (cross-page jump
into the argument grabber). [confirmed]

### DRAW menu commands (page 0x04 handlers)

Each DRAW menu command has a page-04 bcall handler that draws into `plotSScreen`:

| bcall | Addr | Command |
|-------|------|---------|
| `_HorizCmd` | `04:793E` | `Horizontal y` — draws a full-width horizontal line at real Y. See note below. |
| `_VertCmd` | `04:7955` | `Vertical x` — draws a full-height vertical line at real X. See note below. |
| `_LineCmd` | `04:796A` | `Line(x1,y1,x2,y2)` — `_PDspGrph`, optionally draws via page 33, then `JP 0x152A` = `_DeallocFPS1(0x24)` frees the coord frame (the alloc happens upstream). |
| `_UnLineCmd` | `04:797C` | `Line(…,0)` — erase variant (same path, clear mode). |
| `_PointCmd` | `04:79B2` | `Pt-On/Pt-Off/Pt-Change(` — reads style from `OP1.mantissa[0] & 0x20`, dispatches set/clear/toggle. |
| `_DrawCmd` | `04:7B8B` | top-level `DRAW` dispatch — grabs the pending count and cross-jumps to the per-command handler. |
| `_DrawZeroOP1` | `04:620B` | seeds OP3=0 then draws (used for axis / `DrawF` zero baseline). |

Note: `_HorizCmd`/`_VertCmd` both `CALL 7933` first, which allocates a 0x24-byte FPS frame
(`LD HL,0x24 / CALL 1537 / SBC HL,DE`) and returns a pointer to it. `_HorizCmd` then builds the
line's two endpoints in that frame: it copies `Xmin` (`0x8F50`) and `Xmax` (`0x8F59`) — the window's
X range — with `_Mov9B` (`00:1A92`, which reads a window float into the frame), interleaving the
line's Y (`OP1`) via `_MovFrOP1` (`00:1B0C`), so the endpoints are `(Xmin, y)` and `(Xmax, y)`.
`_VertCmd` does the same with `Ymin` (`0x8F6B`)/`Ymax` (`0x8F74`) and the line's X. It renders with
`_PDspGrph`, then `_DeallocFPS1(0x24)` frees the frame — the window variables are read only,
so the line just spans the current window edges. [confirmed]

---

## 5. Rendering the graph to the LCD

`_PDspGrph` (`04:7904`, "possibly-display graph") is the gatekeeper between buffer and
screen. [confirmed]
- Clears the "need redraw" flag at `(IY+2)`,
- if the graph-dirty bit `(IY+3)&1` is set (`graphFlags.graphDraw`, inc `graphFlags=3`/`graphDraw=0`; `1`=redraw needed — this is the `graphFlags` bit at `IY+3`, distinct from `grfDBFlags` at `IY+4` and SmartGraph at `IY+0x17`), calls
  `_Regraph` to recompute the whole plot,
- otherwise checks the split-screen flag (`_Bit_VertSplit`) and copies the buffer to the LCD
  (`graph_redraw_buf` `04:607F`).

`_GrBufCpy` (`04:60A3`) blits `plotSScreen` to the LCD: handles split-screen
(`_CheckSplitFlag`, `_Bit_VertSplit`), draws the split divider line (`_DarkLine`/`_ILine` at
column region 0x2F), sets normal display vals, and walks the rows. [confirmed]

`_RestoreDisp` (`04:6176`) is the actual row-blit loop: for each of the up-to-64 rows it
issues the column/row LCD commands then streams pixel bytes to `port_lcdData` (0x11)
through `lcd_wait`, and pokes `port_lcdCmd` (0x10). This is where the buffer physically
reaches the panel. [confirmed]

`_Regraph` (`04:6764`) re-evaluates and re-plots every selected Y= equation from scratch
(cross-page jump into the plot driver). This is what runs when you change a window var or
turn SmartGraph off; SmartGraph (`grfModeFlags` bit `smartGraph`) lets the OS skip the
re-plot and `_GrBufCpy` the existing buffer when nothing changed. [confirmed]

---

## 6. Y= equations: storage and evaluation

### Storage [confirmed]
Y= functions are ordinary equation variables (`EquObj`), stored in the VAT as tokenized
byte streams — the same token encoding the homescreen uses. `Y1`…`Y0` (and `r1`…, `X1T/Y1T`,
`u/v/w`) are *system* equation vars. Each holds the tokens you typed after `Y1=`. The
equation's flags byte is `0x23` when selected (plotted) and `0x03` when deselected, so
the selection bit is bit 5 (`0x20`). The per-equation style byte holds the line style:
`0`=line, `1`=thick, `2`=shade above, `3`=shade below, `4`=trace/path, `5`=animate, `6`=dotted
(`curGStyle` `0x8D17` is the current-equation copy). [confirmed — selection/style byte values
match the [TI link-protocol guide](https://merthsoft.com/linkguide/ti83+/vars.html#style)]

### Parsing / pre-scan
`_GraphParseTok` (`33:5023`) walks an equation's token stream to classify it before
plotting: it reads tokens via the paged-pointer reader (`_SetupPagedPtr`/`_PagedGet`),
recognizes 2-byte tokens (`_IsA2ByteTok`), and sets feature bits (e.g. token `0xEF…`
ranges → returns a category in A) used to decide draw mode and whether the equation is
graphable. [confirmed]

### Evaluation → points
Plotting (driven by `_Regraph` → the page-04/38 plot loop) walks pixel columns left→right:
1. compute the real `X` for the column from `Xmin + col*deltaX` (the inverse of `_XftoI`),
2. store it into the `X` system variable,
3. `_ParseInp` (`38:5987`) parses+evaluates the selected equation's tokens against the
   current `X` (it resets the parser state, clears a status bit at `(IY+0x1F)`, and runs
   the formula evaluator `_ChkFindSym`/`Find_Parse_Formula`), leaving the result `Y` in OP1,
4. `_YftoI` maps that `Y` to a pixel row,
5. `_ILine` connects this point to the previous column's point (or `_IPoint` for dotted
   style), drawing into `plotSScreen`.
`Xres` (`XresO`/`Xres_int`) controls the column step: Xres=1 evaluates every pixel column,
higher Xres skips columns (faster, coarser). [confirmed]

### Graph databases (GDB) [confirmed]
`_StoGDB2` (`33:71AC`) / `_RclGDB2` (`33:72D9`) store/recall a GraphDataBase
(`GDBObj`, type/exp marker `0x61`) — the bundle of window vars + mode + selected equations
that the `StoreGDB`/`RecallGDB` commands save. `_JError(0x89)` on a type mismatch.

### Graph table [confirmed]
`_GraphTblFind` (`33:7097`) / `_GraphTblNext` (`33:707A`) index the in-RAM table of
equation pointers (`iMathPtr4`-based, 2 bytes/entry) used to iterate the selected functions
during a regraph or TABLE build.

---

## 7. Graph screen vs. home screen; TRACE

- The home screen uses the large font and `curRow`/`curCol` text cursor (see
  [08-display-lcd.md](08-display-lcd.md)). The graph screen is the pixel buffer `plotSScreen` rendered by
  the routines above; small-font labels (coords, TRACE readout) go through
  `_VPutMap`/`penCol`(0x86D7)/`penRow`(0x86D8). [confirmed addresses]
- **TRACE** moves a cursor along a selected function: it steps the column, evaluates the
  function (`_ParseInp`) for that X, maps the point with `_XftoI`/`_YftoI`, draws the
  cross-cursor, and uses `_SetXXOP1`/`_SetXXOP2` to convert the cursor pixel back to the real
  X/Y it prints at the bottom. [confirmed]
- A `DRAW` command (`_DrawCmd`) or `Line(`/`Circle(`/`Pt-On(` draws straight into
  `plotSScreen` over the current plot and persists across a SmartGraph redraw (it is not
  re-evaluated) until `ClrDraw` is issued. [confirmed]

---

## 8. Confidence summary / open items

- Forward transform `(value−min)/pixelDelta`: structure [confirmed] from the
  `37:41F2` disassembly (subtract `228F`, divide `2385`); the exact rounding in `4229` is
  read but the ±sentinel constants are summarized, not exhaustively byte-traced.
- `_HorizCmd`/`_VertCmd` endpoint build — resolved: `7933` allocates a 0x24-byte FPS frame, and
  the commands `_Mov9B` the window edges (`Xmin`/`Xmax` or `Ymin`/`Ymax`) plus `_MovFrOP1` the line's
  coordinate (`OP1`) into that frame, reading the live window variables only.
- Circle parametric stepping in `3B:7171` (`_DrawCirc2`) not decompiled here (lives on
  page 3B); the `_GrphCirc` setup is confirmed.
- Y= selection bit (`0x20`; flags byte `0x23` selected / `0x03` deselected) and the style byte
  values (`0`–`6`) are [confirmed] against the [TI link-protocol var guide](https://merthsoft.com/linkguide/ti83+/vars.html#style).
