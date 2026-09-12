# Matrices and lists

TI-84 Plus OS 2.55MP stores lists and matrices as VAT objects and evaluates
their element, aggregate, and linear-algebra operations through page-`02`
routines. This page covers layout, indexing, arithmetic, sorting, determinant,
inverse, multiplication, and row reduction. [Variables and the
VAT](variables-vat.md), [Floating-point engine](floating-point.md), and
[Variables, archive and unarchive](sub-vat-archive.md) describe the shared
storage and arithmetic layers.

Raw disassembly supplies the banked-page operations that the decompiler does
not reduce reliably.

## Data model

- A list is `word count` (2 bytes) followed by `count` × 9-byte `TIFloat` elements
  (18-byte complex elements if the list is complex, flagged `0x0C`). Element $i$ (1-based)
  lives at $\mathrm{addr}(L_i)=\mathrm{data}+2+(i-1)\cdot 9$.
- A matrix is <code>byte columns</code><br><code>byte rows</code> followed by
  `columns*rows` × 9-byte `TIFloat`, stored row-major. The element offset from the start
  of the data area, after the two dimension bytes, is

  $$\mathrm{offset}=\big((\mathit{row}-1)\cdot \mathit{columns}+(\mathit{column}-1)\big)\times 9$$
- Every element read/write routes one `TIFloat` through `OP1`/`OP2` and the FP engine —
  there is no "vector unit"; matrix multiply is a triple loop of `_FPMult`+`_FPAdd`.
- The data area is found through the VAT (`_FindSym`, [Variables & the VAT](variables-vat.md)): the VAT entry's data
  pointer identifies the `count`/`dim` header for a RAM object. An archived
  pointer first identifies the archive record; its type-aware header must be
  skipped before reading the variable data. `_AdrLEle`/`_AdrMEle` perform
  indexing on the data layout, not on an archive-record header.
- One shared pivoted matrix engine (`02:42A6`) implements matrix inverse `[A]⁻¹`
  (flag `0x00`) and `det(` (flag `0x40`) with partial pivoting. `rref(`/`ref(` are
  the same elimination family.

---

## Data layouts and creator routines [confirmed]

### List — `_CreateRList` (`00:10C4`), `_CreateCList` (`00:1109`)

```text
_CreateRList(count, dataPtrOut):
  reject unless OP1 name token (8478.exp) ∈ {0x5D, 0x24, 0x3A, 0x72}  # list-name classes
  var_alloc(1)                  # internal creator opens count*9 + 2 bytes
  store count word at data[0..1]
  if list is complex (8499.type & 8): data[2] = 0x0C   # element-size flag
```
Layout: `[countLo countHi] [TIFloat e1] [TIFloat e2] …`. A complex list keeps a `0x0C`
flag and 18-byte elements.

### Matrix — `_CreateRMat` (`00:1115`)

```text
_CreateRMat(H=rows, L=columns, dataPtrOut):
  _HTimesL()                    # element count = H * L
  var_alloc(2)                  # carve H*L*9 + 2 bytes
  LD (HL),C                     # write columns
  INC HL
  LD (HL),B                     # write rows
```
- `_HTimesL` (`00:1EF6`) computes `result = H * L` (<code>B=H</code><br><code>HL=Σ L</code>, a `DJNZ` add loop) —
  it computes the element count from the two dimension bytes. [confirmed]
- The header stores `columns,rows`; the payload contains `columns*rows` floats row-major.

> **Dimension naming.** `_CreateRMat` receives `H=rows` and `L=columns`.
> The common header writer at `ram:10E0` recovers those bytes as `B` and `C`,
> then stores `C` before `B` at `ram:10EE`–`ram:10F1`. `_AdrMEle` reads the
> first byte as the stride, adds it `B-1` times, and adds `C-1`. Its public
> register convention is therefore `B=row`, `C=column`, with the offset
> `(row-1)*columns+(column-1)`. [confirmed]

---

## Element access and index-to-offset conversion [confirmed]

Two address-calculators turn a 1-based index into a byte
pointer, then a 9-byte move shuttles the `TIFloat` to/from `OP1`.

### List element address — `_AdrLEle` (`02:47C5`)

```z80
_AdrLEle(index, listDataPtr):           ; HL=index, DE=listDataPtr
  INC DE
  INC DE                        ; skip the 2-byte count header
  A = (DE) & 0x1F                         ; element type (low 5 bits); 0x0C ⇒ complex
  CALL 21C4                               ; classify real vs complex element width
  HL = (index − 1)                        ; _HLTimes9(index-1)
  CALL 1930  (_HLTimes9)                  ; HL = (index-1) * 9
  if saved element type is complex: HL += HL
  HL += DE                                ; final element pointer
```
So list element *i* is at `data + 2 + (i−1)*9` (×18 path for complex). `_HLTimes9`
(`00:1930`) is the universal "multiply by 9" (real `TIFloat` size). `chk_type_lt_1a` (`ram:21C4`) masks the low five type bits and returns carry
for types below `0x18`. `_AdrLEle` then tests `A & 0x0C`; type `0x0C`
doubles the 9-byte offset, while type `0x00` retains it. [confirmed]

Convenience wrappers (all = `_AdrLEle` then a 9-byte move through OP1, complex-aware): [confirmed]
- `_GetLToOP1` (`02:47EA`) — list[i] → OP1 (real or complex via two `_Mov9B`).
- `rcl_list_elem_to_op1` (`02:47FB`), `rcl_list_elem_b` (`02:47FE`) — recall to OP1 with the
  index pre-loaded in RAM (`84AF`/`84D3`).
- `_PutToL` (`02:4829`) — OP1 → list[i]; `_CkValidNum` validates the float first, then
  copies, honoring the complex (`& 0xC`) element width.
- `rcl_c_list_elem` (`02:49A7`), `rcl_c_list_elem_b` (`02:49B5`) — complex-list element via
  `cplx_op_arrange` (splits real/imag into OP1/OP2).
- `get_pos_list_elem` (`02:5BBB`) — fetch by a *positive-integer* index with `_CkOP1Pos`
  bounds (loads `A=0x15` = `E_Stat` and jumps to the error vector `ram:2741` on a bad index).

### Matrix element address — `_AdrMEle` (`02:4002`) [confirmed]

```z80
_AdrMEle:                                 ; B=row, C=column, DE=matrixDataPtr
  if B==0 or C==0 -> LD A,0x78
  JP 0x2793 ; 0-index rejected (error vector)
  A = (DE)        ; A = columns             ; first header byte
  HL = 0
  repeat (B − 1) times:  HL += columns     ; (row-1) * columns
  HL += (C − 1)                            ; + (column-1)
  DE += 2                                  ; skip both dim bytes
  CALL 1930 (_HLTimes9)                    ; HL *= 9
  HL += DE                                 ; final element pointer
```
The row-major address is `data + 2 + ((row-1)*columns + (column-1)) * 9`.
Each `(B-1)` addition skips one complete row, and `C-1` selects an element
within that row. The 8-bit additions propagate carry into `H`. The multiplication and final
pointer addition remain 16-bit operations; valid callers must supply dimensions
and storage whose offsets fit the allocated matrix. [confirmed]

Matrix element wrappers: [confirmed]
- `_AdrMRow` (`02:4000`) — address of the start of row `B`; it sets `C=1` and
  enters `_AdrMEle`.
- `_GetMToOP1` (`02:4044`) — `[M](r,c)` → OP1 (`_AdrMEle` then `RST4` = load 9 bytes).
- `_PutToMat` (`02:406C`) = `mele_store_ckvalid` (`02:4068`): <code>_AdrMEle</code><br><code>_CkValidNum</code><br><code>_MovFrOP1</code> — OP1 →
  `[M](r,c)` with validation.
- `_StMatEl` (`38:6C8F`) — high-level "store into `[M](r,c)`" used by the parser: resolves
  the matrix name (`5F45`), bounds-checks indices against the dims (`r≤rows && c≤cols`, else
  `_JError 0x8C` = `E_Dimension`), unarchives if needed, then `_PutToMat`. [standard]

### Internal index helpers reused by the algorithms [confirmed]

- `mele_adr_af_jp` (`02:403C`) = <code>_AdrMEle(currentIJ)</code><br><code>RST4</code> — "load `[M](i,j)` to OP1" (the elimination
  inner-loop read). Indices come from the loop state at `84AF/84B3/84B4`.
- `mele_adr_to8483` (`02:4051`) = <code>_AdrMEle</code><br><code>_Mov9B(→OP2@8483)</code> — load element to OP2.
- `mele_put_af` (`02:405A`) / `mele_put_d3` (`02:405E`) = <code>_AdrMEle</code><br><code>_CkValidNum</code><br><code>_MovFrOP1</code> — store OP1 back to `[M](i,j)`.
- `list_idx_times9` (`35:79E9`) = `_HLTimes9(idx)` then a small dispatch (`RST4`) — the list
  analogue used in a few list-builder paths.

---

## List operations [standard]

### Creation, resizing, insertion, and deletion

| Routine | addr | Role |
|---|---|---|
| `_CreateRList` | `00:10C4` | new real list: `count*9+2` bytes; see [Data layouts and creator routines](#data-layouts-and-creator-routines-confirmed) [confirmed] |
| `_CreateCList` | `00:1109` | new complex list: `count*18+2` [confirmed] |
| `_IncLstSize` | `07:4EF4` | grow a list in place via `_InsertMem`; caps length at 999 (`0x3E7`), else `E_Dimension 0x8C` (`07:4F00 JP Z,0x2719 → LD A,0x8C`). `_InsertList` is the distinct sibling at `07:4F07`. [confirmed] |
| `_DelListEl` | `07:4F43` | delete element(s): `_HLTimes9(index)` to size the gap (×2 if complex, `& 0x1F == 0x0D`), then `_DelMem` via a cross-page jump [confirmed] |
| `_RedimMat`/`_ConvDim` | `07:4D3B` / `38:741F` | re-dimension (shared with matrices); `_ConvDim`/`_ConvDim00` (`38:741F/7422`) coerce OP1 to a real index first [confirmed] |

### `dim(`, `dim(L)→n`, list↔value

`dim(` reads the `count` word straight from the list header; assigning `n→dim(L)` calls the
resize path (`_IncLstSize`/`_DelListEl`) to grow/shrink, zero-filling new cells.
The list/matrix conversion commands copy values between containers; their
complete caller paths remain open here. [standard]

### List arithmetic `L1+L2`, scalar broadcast

Binary list ops are element-wise folds: the parser walks both lists by index, loads
`L1[i]`→OP1, `L2[i]`→OP2, applies the FP RST shortcut (`RST 30h _FPAdd`, `_FPSub`, `_FPMult`,
`_FPDiv`), stores into a freshly `_CreateRList`'d result. Length mismatch ⇒ `E_DimMismatch`
(`_ErrDimMismatch 00:2715`, `0x8B`); a list⊕scalar broadcasts the scalar across every element. [standard]

### `sum(`, `prod(` — higher-order folds over a list [confirmed]

Tokens `0xB6`=`sum(`, `0xB7`=`prod(` load a *combiner function pointer* and fold the
list (dispatcher `02:6104`):
```text
sum(  : HL = 0x3A83 (cross-page → FP add-accumulate),  seed via _OP1Set0
prod( : HL = 0x49B9 (seed accumulator = 1.0, _PushOP1), combine with _FPMult
        CALL 0x64B7
        ...
        JP (HL)                        # apply the combiner across e1..eN
```
The fold seeds the accumulator (0 for sum, 1 for prod), then for each element does
`acc = combine(acc, L[i])` through OP1/OP2. Works on real and complex lists (`type 1`/`0xD`
both route to `02:6140`). [confirmed]

### Sequence, cumulative, sorting, and statistics operations

- `seq(expr,var,lo,hi[,step])` evaluates the expression at successive variable
  values and builds a result list. The fixture
  `tools/macros/list-seq-eval.macro` exercises `seq(X²,X,1,5,1)`.
  Page-`34` parse-ahead helpers at `34:5AA1`/`34:5BD8` manipulate
  MathPrint token boundaries; their presence does not identify the numeric
  square operation or the list-collection loop. The complete caller-to-collector
  path remains [hypothesis].

- `cumSum(` uses selector `8Dh` and the matrix/list branches described below.
  The list path selects addition with `LD A,70h` at `02:4A02` and calls
  the shared binary-operation dispatcher through `02:47A7`. [confirmed]
- `SortA(`/`SortD(` — list sort in place (`SortA(` co-sorts dependent lists); the comparator
  and per-element sort key are detailed in the next subsection. [confirmed]
- Stats (`mean/median/sum/stdDev/variance`) are list folds layered on `sum(`/sort. [hypothesis]

### `SortA(` and `SortD(` list sorting [confirmed]

`SortA(` (`tSortA` `0xE3`) and `SortD(` (`tSortD` `0xE4`) sort a list in place — ascending and
descending respectively; `SortA(L1,L2,…)` co-sorts the trailing lists by the same permutation. This
is the command sort, distinct from the stat-internal `stat_sort` (`3A:7935`) that backs median/
quartile/Med-Med (see [Statistics](sub-statistics.md)).

The command dispatch is byte-pinned in `list_fold_dispatch` on page `02`.
`CP 0xE3` at `02:6529` (`SortA(`) and `CP 0xE4` at `02:657A` (`SortD(`) converge
on the shared setup at `02:652F`. Register `A` carries the direction: `0x0E` for
ascending and `0x10` for descending. The executor chain checks arguments at
`ram:38BB`, registers the list through `02:5DFB`, and saves the element pointer
from `0x84AF` to `0x84B1`. It then resets the pointer to `1` and enters the
compare/store loop through `02:6A12`. The engine at `02:5939` compares each
element with `_CpOP1OP2` (`00:198D`).

`_CpOP1OP2` compares two `TIFloat`s as real numbers [confirmed]: it tests the
sign (type byte bit 7), then the exponent, then the mantissa digits, and returns the
ordering. It does not compute a magnitude and does not read an imaginary part. Each comparison
therefore orders elements by the single 9-byte `TIFloat` the sort holds in `OP1`/`OP2`:

| List element | Sort key |
|--------------|----------|
| real | the value (sign → magnitude) |
| complex | Command acceptance, element loading, and equal-key ordering remain unverified. |

The comparator alone does not establish whether the command accepts complex
lists, which component its caller loads, or whether equal keys retain input
order. Those command-level properties remain [hypothesis].

### Traceable list sample

The `tools/tibasic-samples/data.*` fixture drives the list paths above with a
small end-to-end TI-BASIC program:

```ti-basic
{3,1,4,1,5}->L1
SortA(L1)
cumSum(L1)->L2
sum(L1)->S
Disp L1
Disp L2
Disp S
```

It exercises list literal creation, list variable tokens (`5D 00`/`5D 01`),
in-place sorting, a running cumulative sum, a folded sum, and list display. The
generated `DATA.8xp` was run under headless TilEm: the screen showed sorted
`L1={1 1 3 4 5}`, cumulative `L2={1 2 5 9 14}`, and sum `14`; the trace hit
`list_fold_dispatch` (`02:6104`) plus the page-38 list parse/store helpers. [confirmed]

---

## Matrix operations [confirmed]

### `dim(`, redim, identity, copy

- `dim([M])` reads the two header bytes → a 2-element list `{rows,cols}`; `{r,c}→dim([M])`
  reallocates via `_RedimMat` (`07:4D3B`), preserving overlapping cells and zero-filling new
  ones. [standard]
- `identity(n)` (token `0xB4` → `identity_build` (`02:4108`)) [confirmed]: allocate `n×n`, then walk every cell
  writing `1.0` when `row==col` (the `exp==type` test) and `0` otherwise:
  ```z80
  _OP1Set1 ; for each (i,j): if i==j -> store 1.0 (mantissa[0]=0x10) else 0
  ```
- `Fill(value,[M])` / `randM(` fill the matrix with a constant or random values.
  The `02:62D4` branch handles `dim(` and returns dimensions; it does not fill
  or resize the source matrix. For the decoded `randM(` fill see
  [The `randM(` cell fill](#the-randm-cell-fill-confirmed).
- Matrix copy/reshape = `_DataSize`-counted byte copy of the float payload
  (`mele_copy9_d3` (`02:4539`)/`mele_copy9_loop` (`02:453F`)). [confirmed]

### The `randM(` cell fill [confirmed]

`randM(rows,cols)` builds its `r×c` result through the internal matrix creator
at `00:110F` (the public `_CreateRMat` entry is `00:1115`). It fills
each cell with $\operatorname{int}(19\cdot\operatorname{rand})-9$, matching the
documented integer range $[-9,9]$. The loop is byte-pinned at
`02:5CC1`–`02:5CE6`. A headless TilEm trace of `randM(3,3)` executes this path
(`tools/macros/matrix-randm.macro`):

```z80
02:5CC1 loop:
  PUSH BC / PUSH DE           ; save cell counter and element pointer
5CC3: CALL ram:392D           ; banked-call stub -> _Random (36:7DC9); OP1 = uniform [0,1)
      LD A,0x13               ; 19 decimal
      CALL ram:389D           ; banked-call stub -> 33:5F83; load small int A as FP operand
      CALL _FPMult   (238B)   ; OP1 = 19·rand
      CALL _Intgr    (2263)   ; truncate -> {0..18}
      LD A,0x09               ; 9 decimal
      CALL ram:389D           ; second operand = 9
      CALL _FPSub    (2297)   ; OP1 = int(19·rand) - 9 in [-9, 9]
      POP DE                  ; advance element pointer by one float cell
      CALL 1B0C               ; store OP1 into the matrix element
      LD HL,-18 / ADD HL,DE   ; step to the next 9-byte cell
      POP BC / DEC BC         ; cells remaining--
      JR NZ,loop
```

The loop reaches `_Random` (`0x4B79` → `36:7DC9`) through a page 0 banked-call
stub table. It does not use an `RST 28h` bcall site, so a ROM-wide scan for
<code>RST 28h</code><br><code>.dw 0x4B79</code> finds no match. The stub at `ram:392D` contains `CALL 2B09`
followed by the inline descriptor <code>.dw 0x7DC9</code><br><code>.db 0x76</code>. The trampoline writes
the descriptor's page byte to port 6. Bit 7 clear selects flash, and the low six
bits select the page, so `0x76` selects page `36`. Static descriptor scans must
mask the page byte with `0x3F`. The small-integer loader stub at `ram:389D`
targets `33:5F83` through the same mechanism. [confirmed]

### `[A] + [B]`, `[A] - [B]`, scalar·[A] — element-wise [standard]

Binary matrix add/sub apply the FP operation through a nested walk:

```text
for each column:
  for each row:
    load [M](r,c) -> OP1
    apply the FP operation
    store the result
```

The operation requires equal dimensions (`_ErrDimMismatch 0x8B`). The nested two-counter cell
walk at `02:412A` is the transpose copy (§ transpose); the add/sub element-loop driver is a
sibling in the same `412A`–`414E` family and is inferred here. [standard]

### `[A] * [B]` — matrix multiply [confirmed]

The multiply body is at `02:40BA`. It is not a defined function in the disassembly (so the
decompiler/MCP can't reach it), so this was decoded from `rom.bin` directly with `z80dasm`,
cross-checked against a routine Ghidra *does* define. The body is called from `02:5FFF` (the
`*` operator handler, in the `02:5FE6` region) and reused from `02:4605` and `02:5B39`. (`0x40BA`
is also the `_SinCosRad` bcall ID in ti83plus.inc — a hex coincidence, unrelated to this page-02
address.)

`40BA` is a classic O(n³) triple loop with an FP accumulator:
```text
for each result cell (i,j):                  # counters at 84B7, 84B4
    for k = 1 .. inner:                      # inner counter at 84AF
        load [A](i,k)          (403C mele_adr_af_jp)
        multiply by [B](k,j)   (47B9 / 0166F  FP multiply)
        accumulate             (479F)
    store acc -> [C](i,j)      (4064 / 405A)
```
The three `dec (hl)` counters (`84AF` inner, `84B4`, `84B7`) each have a `jr nz` back-edge
(`40E5`, `40F9`, `4100`); an inner-dim mismatch (`A.cols ≠ B.rows`) raises `_ErrDimMismatch`. An
`n×n` product is `n³` `TIFloat` multiply+add steps. [confirmed] The body comes
from direct `rom.bin` decoding; callers `02:5FFF`, `02:4605`, and `02:5B39`
are byte-verified.

### Transpose `[A]ᵀ` — `02:412A`, dispatched from the `ᵀ` token `0x0E` [confirmed]

The transpose operator `ᵀ` is the postfix token `tTrnspos` = `0x0E`. The page-02 command
dispatcher handles it at `02:60E9` (`CP 0x0E`). It requires one matrix operand by testing
`CP 0x02` followed by `JR NZ`. At `02:60F5`, it swaps the two dimension bytes for the result
header with `LD A,H`, `LD H,L`, and `LD L,A`, then
allocates the transposed-shape matrix (`5DBB`/`5DE0`), runs the per-cell copy body at `02:412A`,
then stores via `JP 0x5F89`. `02:412A` has exactly one caller, `02:60FE` (byte-verified `CD 2A 41`).

`02:412A` is the transpose copy [confirmed]. It walks every source cell and writes the value into the
destination whose `_AdrMEle` stride is the *swapped* dimension, so `dst(c,r) = src(r,c)`:
```z80
412A: LD HL,(84AF)              ; loop counters = dims
412E: CALL 403C                 ; load src [M] (B=row,C=column) from (84D3) → OP1
4131: LD HL,(84AF)
LD B,L
LD C,H
4136: CALL 4068                 ; store OP1 → dst [M] via dest ptr (84D7)
4139: DEC (84AF)
JR NZ,412E   ; inner counter
4141: LD (HL),C
INC HL
DEC (HL)
JR NZ,412E  ; outer counter
4146: POP HL
LD B,L
LD C,H
RET
```
`403C` reads from the source data pointer `(84D3)`; `4068` writes to the destination pointer
`(84D7)`. The destination header carries the dimensions swapped by `02:60F5`.
The row-major `_AdrMEle` calls therefore place `src(r,c)` at `dst(c,r)`. [confirmed]

`02:4178` (`mat_fill_type1`) is a separate single-counter fill/apply in the `414A`–`4178` block,
not the transpose body. [confirmed]

### Function selectors and shared drivers [confirmed]

The parser normalizes part of the `BB` token family before page-`02`
execution. At `38:6FB2`, `ADD A,64h` maps `BB 25`–`BB 2E`
to selectors `89h`–`92h`. A compare operand in this range is therefore
not a literal single-byte source token.

| Source token | Selector and dispatch | Established behavior |
|-------------|-----------------------|----------------------|
| `BB 29`, `cumSum(` | `8Dh` at `02:6388` | Matrix-type path calls `02:4773`; list path calls `02:49E3`. |
| `BB 2A`, `expr(` | `8Eh` at `02:61C1` | Requires a string, copies its payload into parser storage, and calls the parser stub at `ram:391B`. |
| `BB 2D`, `ref(` | `91h` at `02:635B` | Sets carry before entering `02:4663`. |
| `BB 2E`, `rref(` | `92h` at `02:637F` | Clears carry before entering the same engine. |
| `B5`, `dim(` | `B5h` at `02:62D4` | Returns a two-element dimension list for a matrix, or a scalar count for a list. |
| `0E`, transpose | `0Eh` at `02:60E9` | Swaps dimensions and calls the transpose copy at `02:412A`. |

The matrix `dim(` path saves the matrix dimensions, allocates a list of
length two at `02:62E1`–`02:62E4`, and stores its entries at
`02:62EF` and `02:62F9`. The `CP 02h` at `02:62D9` tests the
operand's matrix type; it is not an argument-count test.

`02:6238` preserves dimensions, allocates/copies matrix storage when
necessary, and updates `iMathPtr1` at `0x84D3`. Its use before row
reduction does not make it an `augment(` implementation.
`augment(` is single-byte token `14h`; `Matr►list(` and
`List►matr(` are `BB 39` and `BB 3A`. Their full execution paths
remain open here.

---

## Determinant, inverse, and row reduction [confirmed]

`det(` and `[A]⁻¹` share a matrix engine with partial pivoting —
`matrix_gauss_engine` @ `02:42A6` — the *entry flag in `A`* selecting behaviour; only two
direct call sites exist (byte-verified — `CD A6 42` appears exactly twice). `rref(`/`ref(` are a
separate driver and do not call `42A6` (see below):

| Token / op | site | flag `A` | meaning |
|---|---|---|---|
| `[A]⁻¹` (reciprocal token `0x0C`, operand = matrix) | `02:5F80` | `0x00` | inverse; singular ⇒ error |
| `det(` (token `0xB3`) | `02:5FC0` | `0x40` | determinant; bit6 set ⇒ singular tolerated (returns 0) |

`det(`'s handler at `02:5FA3` (not a defined function in the disassembly; address
unverified) first type-checks the operand is a matrix (`chk_op_is_matrix` (`02:69B7`):
`type==2 else E_DataType 0x89`), then <code>LD A,0x40</code><br><code>CALL 0x42A6</code>.

### The engine (`42A6`) [confirmed]

The following phases are pinned by their instructions. They do not yet
establish a complete named factorization recurrence or an augmented-identity
implementation:

- `02:42A7`–`02:42BC` requires a square matrix and handles the `1×1`
  case directly; inverse mode calls `_FPRecip` for that scalar. A zero
  scalar therefore reaches the reciprocal's DIVIDE BY 0 error, not the
  later failed-pivot SINGULAR MAT branch.
- `02:42C4` calls the maximum-magnitude helper at `02:461C`.
  Inverse mode initializes the permutation vector at `02:42D8`–`02:42E3`.
- The work loop forms dot products through `02:426D` and subtracts them
  from a selected matrix element through `02:4473` (calls at `02:4319`
  and `02:431C`). A separate branch divides a work value by a diagonal
  element at `02:4348` and writes it back.
- The pivot scan at `02:41D0` compares magnitudes and swaps rows through
  `02:43B9`/`02:414E`. It tracks swap parity in the saved mode byte;
  inverse mode also updates the permutation vector.
- The failed-pivot path at `02:43A1` tests mode bit 6. Inverse mode raises
  `_ErrSingularMat`; determinant mode discards work and returns zero.
- Determinant mode reaches the diagonal-product tail at `02:43DD`.
  Inverse mode sets phase bit 5 and re-enters the work loop at `02:440A`,
  then performs the arithmetic passes at `02:4410`–`02:446F` and the
  permutation undo at `02:4470`.
Key sub-routines (all `page_02`; names are the live Ghidra DB labels): [confirmed]
- `461C` `mat_max_abs` — compute the matrix's max-abs element (numeric scale for the
  near-zero pivot test).
- `41C1` `abs_cmp_op1op2` — `|OP1|` vs `|pivot|` compare (`1A0F`/`1987` abs+compare);
  `41D0` — scan a column for the largest-magnitude pivot (partial pivoting), calling
  `43B9` to swap rows as it goes.
- `43B9` / `414E` `mrow_swap_loop` / `_AdrMRow` — physical row swap / row scale
  (whole-row moves; `414E` loads the column-count stride and swaps two complete rows via `_AdrMRow`×2 +
  `1DDA`).
- `4259` — swap two entries in the permutation vector at `84D5`.
- `4473` `ele_sub_ref` — subtract the current accumulated value from a selected matrix element:
  <code>RST8</code><br><code>CALL 403C</code><br><code>JP 2297</code> = load + `_FPSub`.
- `426D` `col_dot_accum` / `426F` `col_dot_accum_from` — column dot-product / back-
  substitution accumulate (`_FPMult` + `RST6`).
- Work-value division uses `_FPDiv`; sign/inverse paths use `_InvOP1S`.

`det(` therefore = forward elimination with partial pivoting, return the signed product
of the pivots (each row swap flips the sign); a zero pivot ⇒ `det = 0` (no error).
The inverse path has additional arithmetic and permutation passes; a failed
pivot test raises `ERR:SINGULAR MAT`. Calling it full Gauss-Jordan or a
particular LU variant requires a complete recurrence decode. [hypothesis]

#### Determinant sign and pivot-product bytes (`02:43D8`–`02:4470`) [confirmed]

The determinant sign comes from bit 0 of the saved mode byte. The pivot scan
toggles that bit with `XOR 01h` at `02:4201` when it swaps rows.
Determinant mode skips permutation-vector initialization at `02:42D6` and
the vector swap at `02:43BB` (`CALL Z,4259` after testing mode bit 6).
The vector is used by the inverse path. The determinant magnitude is the
product of the diagonal pivots in the tail below:
```z80
43D8 (det branch, bit6 = det):
  43D9: BIT 6,A           ; det mode?
  43DE: CALL 151B         ; pop pivot
  43E3..43F6: PUSH AF ; (RST 8 _CpyToOP2)
  CALL 403c (load [M](i,j)) ;
              CALL 238b (_FPMult)
              DEC pivot/row counters (84B0)  ; loop
              → multiply the running determinant by each pivot
  43F8: POP AF
  AND 1
  JP NZ,24bd    ;  *** DET SIGN ***  low bit of the
              ; saved row-swap parity → conditional _InvOP1S (negate)
43FF (inverse branch): re-walk for the augmented-identity columns,
  4410..446F: per-column back-substitution (4428/445B = _FPMult-accumulate,
              442B/24bd = _InvOP1S sign flips), then JP 0x420F to undo the
              column permutation (4259-pairs) so the inverse comes out in the
              original row/col order.
```
`02:43F9` tests the saved parity bit and `02:43FB` conditionally negates
the determinant through `_InvOP1S` (`00:24BD`). The diagonal-product loop
at `02:43E7`–`02:43F6` uses `_FPMult`, not `_FPAdd`.
The separate negation at `02:442B` belongs to inverse back-substitution;
the permutation undo at `02:420F` restores the inverse's element order.
[confirmed]

### Separate `rref(` and `ref(` driver [confirmed]

`_ROWECHELON = 462Ah` resolves directly from table bytes `63 46 02`
to `02:4663`. The normalized `ref(` and `rref(` branches above
also call this body directly at `02:6379`.

The shared setup requires a matrix. It accepts equal row/column counts or
more columns than rows: `02:636E` compares rows with columns, and
`02:6371` rejects a greater row count with `_ErrDimension`.
The engine selects pivot rows through `02:41D0`, normalizes a pivot row
through `_FPDiv` at `02:46C5`, and stores each normalized element
through `02:405E`. [confirmed]

Carry distinguishes the elimination ranges. At `02:46DC`, carry set
(`ref(`) skips the above-pivot loop at `02:46DE`–`02:46ED`.
Both modes continue through the below-pivot loop at
`02:46EF`–`02:470D`; carry clear (`rref(`) therefore eliminates
above and below the pivot. The helper at `02:471C` performs the row
update. This establishes the distinction without inferring it from the
routine name. [confirmed]

The single-byte `2Dh` branch at `02:609A` calls
`_Factorial = 4B85h`, body `35:7995`. It is unrelated to the
two-byte `BB 2D` row-reduction token. Likewise `4B88h` is
`_YONOFF` at `02:7C23`, not an `rref(` evaluator.

---

## Floating-point and VAT integration [confirmed]

- Every element is a `TIFloat` ([Floating-point](floating-point.md)). Indexing produces a *pointer*; the value is then
  moved into `OP1`/`OP2` (`RST4` = load-9, `_Mov9B`, `_MovFrOP1`) and all arithmetic is the FP
  engine's `RST 30h`(`_FPAdd`)/`_FPMult`/`_FPDiv`/`_FPSub`/`_FPRecip`. There is no SIMD; a
  matrix multiply makes thousands of these calls. Complex list elements carry a
  `0x0C` flag and use 18-byte (two-float) elements, split via `cplx_op_arrange`.
- **Where the data lives:** the parser resolves the list/matrix name through `OP1` →
  `_FindSym`/`_ChkFindSym` ([Variables & the VAT](variables-vat.md)/sub-vat) → VAT entry → data pointer (+ flash page if
  archived). The `count`/`dim` header is read first; then `_AdrLEle`/`_AdrMEle` do pointer
  math. A store into an archived matrix/list unarchives to RAM first (`_Arc_Unarc`;
  Flash cannot be written in place).
- **Scratch RAM used by the algorithms** (verified operands): `84AF` (current dims / i,j loop
  state), `84B0/84B3/84B4` (pivot, k, row counters), `84B7` (dims copy), `84D3/84D5/84D7`
  (data pointers + the permutation vector base), `8478`=OP1, `8483`=OP2, `8499`=OP4,
  `84AF`=OP6 region = the matrix-op loop frame.

---

## Errors [confirmed]

The list/matrix routines raise these `_JError` codes; each row gives the code, its name,
and the routine and condition that triggers it.

| `_JError` code | name | raised by |
|---|---|---|
| `0x78` | 0-index reject (via `ram:2793`) | `_AdrMEle`/`_AdrMRow` on a 0 row/col index |
| `0x83` | `E_SingularMat` (`ERR:SINGULAR MAT`) | `42A6` inverse on a zero pivot (`_ErrSingularMat 00:26F0`) |
| `0x85` | `E_Increment` | `_ErrIncrement 00:26F8` (bad seq/loop step) |
| `0x89` | `E_DataType` | `det(`/matrix ops on a non-matrix operand (`chk_op_is_matrix` (`02:69B7`)) |
| `0x8B` | `E_DimMismatch` (`ERR:DIM MISMATCH`) | add/sub/multiply with incompatible dims (`_ErrDimMismatch 00:2715`) |
| `0x8C` | `E_Dimension` (`ERR:INVALID DIM`) | non-square det/inverse, out-of-range element store (`_ErrDimension 00:2719`, `_StMatEl`) |
| `0x15` | `E_Stat` (via `ram:2741`) | `get_pos_list_elem` bad index (`_CkOP1Pos`) |

---

## Routine index

| space:addr | name | what |
|---|---|---|
| `00:10C4` | `_CreateRList` | new real list (`count*9+2`) [confirmed] |
| `00:1109` | `_CreateCList` | new complex list (`count*18+2`) [confirmed] |
| `00:1115` | `_CreateRMat` | new matrix (`H*L*9+2`, header `columns,rows`) [confirmed] |
| `00:1EF6` | `_HTimesL` | element count = H*L (dims multiplied) [confirmed] |
| `00:1930` | `_HLTimes9` | ×9 (real `TIFloat` stride) [confirmed] |
| `02:4000` | `_AdrMRow` | address of matrix row start [confirmed] |
| `02:4002` | `_AdrMEle` | matrix element address: `((row-1)*columns+(column-1))*9` [confirmed] |
| `02:4044` | `_GetMToOP1` | `[M](i,j)` → OP1 [confirmed] |
| `02:406C` | `_PutToMat` | OP1 → `[M](i,j)` (validated) [confirmed] |
| `02:40BA` | matrix-multiply body | O(n³) triple loop, decoded from `rom.bin` (not a defined function in the disassembly); called from `02:5FFF`/`4605`/`5B39`. `0x40BA` in ti83plus.inc is the unrelated `_SinCosRad` bcall ID. [confirmed] |
| `02:4108` | `identity_build` | `identity(n)`: diagonal-1 fill (token 0xB4) [confirmed] |
| `02:412A` | `mat_transpose` | transpose `[A]ᵀ` body (token `0x0E`, dispatched `60E9`/called `60FE`): per-cell copy `dst(c,r)=src(r,c)` via the swapped dest header [confirmed] |
| `02:414E` | `mrow_swap_loop` | row swap/scale (elimination) [confirmed] |
| `02:4178` | `mat_fill_type1` | live DB name; single-counter per-cell fill/apply loop in the `414A`–`4178` block — not transpose [confirmed] |
| `02:4539` | `mele_copy9_d3` | bulk row-major float-payload copy (skip 2 dim bytes, `LDIR`); used when preparing matrix work storage [confirmed] |
| `02:5264` | `cplx_swap_dispatch` | live DB name; complex OP-pair arrange/swap (`5344`/`52D3`) reached only from the `0xBD` branch (`62D0`) — not the `0xB5`/`dim(` matrix-create branch [confirmed] |
| `02:41C1` | `abs_cmp_op1op2` | absolute-value compare: OP1 vs pivot [confirmed] |
| `02:41D0` | `pivot_col_scan` | partial-pivot: find largest absolute value in column [confirmed] |
| `02:4259` | `perm_swap` | swap two entries of the permutation vector (84D5) [confirmed] |
| `02:426D`/`426F` | `col_dot_accum`/`col_dot_accum_from` | column dot-product / back-substitution accumulate [confirmed] |
| `02:42A6` | `matrix_gauss_engine` | inverse(flag 0)/det(flag 0x40) pivoted matrix engine; square-only (`H==L` guard) [confirmed] |
| `02:4473` | `ele_sub_ref` | `[M] − factor*pivot` element step (`_FPSub`) [confirmed] |
| `02:461C` | `mat_max_abs` | maximum absolute element (pivot tolerance) [confirmed] |
| `02:47C5` | `_AdrLEle` | list element address: `data+2+(i-1)*9` [confirmed] |
| `02:47EA` | `_GetLToOP1` | list[i] → OP1 (complex-aware) [confirmed] |
| `02:47FB` | `rcl_list_elem_to_op1` | recall list elem to OP1 [confirmed] |
| `02:47FE` | `rcl_list_elem_b` | recall list elem (B-indexed) [confirmed] |
| `02:4829` | `_PutToL` | OP1 → list[i] (validated, complex-aware) [confirmed] |
| `02:49A7` | `rcl_c_list_elem` | complex-list element → OP1/OP2 [confirmed] |
| `02:49B5` | `rcl_c_list_elem_b` | complex-list element (B-indexed) [confirmed] |
| `02:5BBB` | `get_pos_list_elem` | list element by positive index (bounds) [confirmed] |
| `02:5E46` | `func_eval_dispatch` | single-byte function-token evaluator (0xB0–0xCD) [confirmed] |
| `02:5F80` | `mat_inverse_entry` | `[A]⁻¹`: flag 0 → `matrix_gauss_engine` [confirmed] |
| `02:5FC0` | `det_entry` | `det(`: flag 0x40 → `matrix_gauss_engine` [confirmed] |
| `02:6104` | `list_fold_dispatch` | `sum(`/`prod(` higher-order list fold [confirmed] |
| `02:69B7` | `chk_op_is_matrix` | require operand type==2 else E_DataType [confirmed] |
| `35:79E9` | `list_idx_times9` | list index ×9 + dispatch [confirmed] |
| `07:4D3B` | `_RedimMat` | re-dimension matrix/list [confirmed] |
| `07:4F43` | `_DelListEl` | delete list element(s) [confirmed] |
| `38:6C8F` | `_StMatEl` | parser store into `[M](r,c)` (bounds-checked) [confirmed] |
| `38:741F`/`7422` | `_ConvDim`/`_ConvDim00` | coerce a dim/index to real [confirmed] |
| `00:26F0` | `_ErrSingularMat` | `E_SingularMat 0x83` [confirmed] |
| `00:26F8` | `_ErrIncrement` | `E_Increment 0x85` [confirmed] |
| `00:2715` | `_ErrDimMismatch` | `E_DimMismatch 0x8B` [confirmed] |
| `00:2719` | `_ErrDimension` | `E_Dimension 0x8C` [confirmed] |

---

## Resolved behavior and remaining questions

The dimensions, element-address formulas, transpose copy, matrix multiplication,
determinant/inverse mode flag, and the `ref(`/`rref(` carry-controlled
elimination ranges have ROM evidence above. The normalized function selectors
must be distinguished from source-token bytes. [confirmed]

The remaining gaps include the complete `seq(` collector, command-sort
complex acceptance and stability, `augment(` and list/matrix conversion
callers, and error-path behavior for arbitrary dimensions and moving VAT
objects. The scalar comparator and direct-call census do not close those
caller-level questions.
