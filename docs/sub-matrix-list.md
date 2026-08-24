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
- A matrix is <code>byte dim0</code><br><code>byte dim1</code> (two 1-byte dimensions) followed by
  `dim0*dim1` × 9-byte `TIFloat`, stored column-major. The element offset from the start
  of the data area (after the 2 dim bytes) is

  $$\mathrm{offset}=\big((\mathit{idx}_0-1)\cdot \mathit{dim}_0+(\mathit{idx}_1-1)\big)\times 9$$
- Every element read/write routes one `TIFloat` through `OP1`/`OP2` and the FP engine —
  there is no "vector unit"; matrix multiply is a triple loop of `_FPMult`+`_FPAdd`.
- The data area is found through the VAT (`_FindSym`, [Variables & the VAT](variables-vat.md)): the VAT entry's data
  pointer + page byte locate the `count`/`dim` header, after which all indexing is pointer
  arithmetic computed by `_AdrLEle`/`_AdrMEle`.
- One shared Gauss-Jordan engine (`02:42A6`) implements matrix inverse `[A]⁻¹`
  (flag `0x00`) and `det(` (flag `0x40`) with partial pivoting. `rref(`/`ref(` are
  the same elimination family.

---

## Data layouts and creator routines [confirmed]

### List — `_CreateRList` (`00:10C4`), `_CreateCList` (`00:1109`)

```text
_CreateRList(count, dataPtrOut):
  reject unless OP1 name token (8478.exp) ∈ {0x5D, 0x24, 0x3A, 0x72}  # list-name classes
  var_alloc(1)                  # carve count*9 + 2 bytes via _InsertMem
  store count word at data[0..1]
  if list is complex (8499.type & 8): data[2] = 0x0C   # element-size flag
```
Layout: `[countLo countHi] [TIFloat e1] [TIFloat e2] …`. A complex list keeps a `0x0C`
flag and 18-byte elements.

### Matrix — `_CreateRMat` (`00:1115`)

```text
_CreateRMat(dimWord, dataPtrOut):
  _HTimesL()                    # element count = H * L
  var_alloc(2)                  # carve H*L*9 + 2 bytes
  LD (HL),C                     # write dim0
  INC HL
  LD (HL),B                     # write dim1
```
- `_HTimesL` (`00:1EF6`) computes `result = H * L` (<code>B=H</code><br><code>HL=Σ L</code>, a `DJNZ` add loop) —
  it computes the element count from the two dimension bytes. [confirmed]
- Header = two bytes `dim0,dim1`; data is `dim0*dim1` floats column-major.

> **Dimension naming.** [confirmed] Settled by disassembly. `_AdrMEle` (`02:4002`) reads the header's
> first byte (<code>LD A,(DE)</code><br><code>LD L,A</code>) and uses it as the major stride, looping `(B−1)`
> adds of it and then `+(C−1)` *within* a column (column-major). The major stride of a
> column-major array is the number of rows, so the first header byte (`dim0`) = #rows,
> and `_AdrMEle`'s `B = idx0 = column`, `C = idx1 = row`. `_CreateRMat` (`ram:1115`) confirms
> the layout: it is <code>PUSH HL</code><br><code>CALL _HTimesL (1EF6)</code><br><code>LD A,2</code><br><code>JR 10DD</code> — `_HTimesL` returns
> `H·L` (the element count) and `A=2` is the 2-byte dim header; the two dimension bytes are
> stored `dim0` (rows) then `dim1` (cols). The byte-confirmed index arithmetic
> `((idx0−1)·dim0 + (idx1−1))·9` is therefore a (column, row) register convention with a row-count stride.

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
  HL += DE                                ; final element pointer
```
So list element *i* is at `data + 2 + (i−1)*9` (×18 path for complex). `_HLTimes9`
(`00:1930`) is the universal "multiply by 9" (real `TIFloat` size). `chk_type_lt_1a` (`ram:21C4`)
masks the type to ≤0x19 and sets carry for the complex case (drives the 18-byte width). [confirmed]

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
_AdrMEle:                                 ; B=column idx0, C=row idx1, DE=matrixDataPtr
  if B==0 or C==0 -> LD A,0x78
  JP 0x2793 ; 0-index rejected (error vector)
  A = (DE)        ; A = dim0 (rows)        ; first header byte
  HL = 0
  repeat (B − 1) times:  HL += dim0        ; (idx0-1) * dim0     (column stride)
  HL += (C − 1)                            ; + (idx1-1)          (within column)
  DE += 2                                  ; skip both dim bytes
  CALL 1930 (_HLTimes9)                    ; HL *= 9
  HL += DE                                 ; final element pointer
```
Column-major offset: `elem = data + 2 + ((idx0−1)*dim0 + (idx1−1)) * 9`. The `(B-1)`
adds of `dim0` walk whole columns; the `(C-1)` steps within a column. The 8-bit adds track
a carry into `H` so the address is a true 16-bit offset (matrices up to 99×99). Because the
multiplied byte is `dim0` and that is the row count (column-major major stride), `B=idx0`
is the column index and `C=idx1` is the row index; see [Data layouts and creator routines](#data-layouts-and-creator-routines-confirmed). [confirmed]

Matrix element wrappers: [confirmed]
- `_AdrMRow` (`02:4000`) — address of the *start of column idx0* in the column-major buffer
  (loops `(idx0−1)` × dim0, no `+(idx1-1)`); whole-row operations layer their own iteration on top.
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
resize path (`_IncLstSize`/`_DelListEl`) to grow/shrink, zero-filling new cells. List→matrix
and matrix→list (`List►matr(`, `Matr►list(`) reshape via `_DataSize` + a column-major copy
(`mele_copy9_d3` (`02:4539`)/`mele_copy9_loop` (`02:453F`), a `_DataSize`-counted byte copy of the float payload). [standard]

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

- `seq(expr,var,lo,hi[,step])` evaluates `expr` for `var = lo..hi`, pushing each result
  and finally `_CreateRList`-ing the collected floats; `_SetSeqM 36:7D1F` is the
  sequence-graph variant. A trace of `seq(X²,X,1,5,1)` produced `{1 4 9 16 25}` and
  mapped the collection path (`tools/macros/list-seq-eval.macro`). Each element enters
  through `cross_page_jump` at `37:6E87`. The parser setup at `38:5B3C` evaluates
  the expression, with `34:5AA1` and `34:5BD8` computing X². The append path runs
  through `02:69BC` and `37:4260`–`37:4285`; it addresses list elements through
  `00:150F` and `00:154F` and compares them at `00:198D`. Page `07` VAT routines at
  `07:565F`, `07:5662`, and `07:5683` grow the storage. After the last element,
  `37:70DC` calls `_CreateRList` at `00:10C4`. The trace contains one collection cycle
  per element, with a period of roughly 2,000 instructions repeated five times.
  [confirmed] The `02:5E14`–`02:5F5D` span is the command-executor dispatch shared by
  every evaluated command; it is not the `seq(` collection loop.
- `cumSum(` is a running `_FPAdd` writing back each partial sum (the sum-fold with the
  accumulator stored every step). [hypothesis]
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
| complex | the real part only; the imaginary part is not read, and elements with equal real parts keep their input order |

No element type is ordered by magnitude/modulus (`_CAbs` is never on this path). [comparator and
its real-number semantics confirmed; the per-element sort key follows from them — the unanalyzed
sort body's element-load is not byte-traced]

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
- `Fill(value,[M])` / `randM(` stamp a constant / random values across all cells via a
  per-cell loop over the whole matrix. The `02:62D4` branch (`CP 0xB5`) is `dim(` (`0xB5` =
  `tDim`), which creates the `r×c` result (`5DBB` → `_CreateRMat 110F`) and stores the dims
  (`631B`/`631C`/`4825`) but performs no fill. For the decoded `randM(` fill see
  [The `randM(` cell fill](#the-randm-cell-fill-confirmed).
- Matrix copy/reshape = `_DataSize`-counted byte copy of the float payload
  (`mele_copy9_d3` (`02:4539`)/`mele_copy9_loop` (`02:453F`)). [confirmed]

### The `randM(` cell fill [confirmed]

`randM(rows,cols)` builds its `r×c` result through `_CreateRMat` (`00:110F`). It fills
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
412E: CALL 403C                 ; load src [M] (B=col,C=row) from (84D3) → OP1
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
`(84D7)`. Because the destination header carries the dims swapped (the `60F5` swap), `_AdrMEle`
(`4002`) computes the column-major offset with the row/column roles exchanged, so the same linear
walk lands element `src(r,c)` at `dst(c,r)` — a true transpose, which re-indexes *both* `i` and
`j`. [confirmed]

`02:4178` (`mat_fill_type1`) is a separate single-counter fill/apply in the `414A`–`4178` block,
not the transpose body. [confirmed]

### `augment(`, `dim(`, `List►matr(`, `Matr►list(` — per-function drivers [standard]

These are dispatched from the page-02 function-token evaluator (`list_fold_dispatch`, the
<code>CP imm</code><br><code>JR/JP</code> chain that runs `5E46`/`60C8`–`63xx`, keyed on the token byte). Each command's
body and its single caller are byte-verified below.

| Command | dispatch site | body | what the disassembly shows |
|---|---|---|---|
| `Matr►list(` | `0x8D` @ `6388` | `02:4773` (2-arg), `02:49E3` (1-arg list copy) | [confirmed] The `0x8D` branch splits on argument count (`638D: CP 0x02`). The column-extract engine is `02:4773` (2-arg path: <code>639D: CALL 5DD8</code><br><code>CALL 4773</code>; only caller `63A0`, byte-verified `CD 73 47`): it nests a per-row loop (`477B: LD B,1 …`, reading via `4040` `_AdrMRow`/`4068` `mele_store_ckvalid`) inside a column loop over `(84AF)`, copying matrix columns into list element(s) (`4051`/`479F`). The 1-arg/list path uses `02:49E3` (`6397: CALL 0x49E3`), a list-element copy-until-length-match (`47E6` recall, `4825` store, `21BB` compare vs `(84AF)`, `RET Z`). |
| transpose `ᵀ` | `0x0E` @ `60E9` | `02:412A` | [confirmed] Swaps the dim header (`60F5`), allocates the transposed shape, then `412A` copies `dst(c,r)=src(r,c)` over every cell (`403C` read from `(84D3)`, `4068` write to `(84D7)`); only caller `60FE`. See the transpose subsection above. |
| `augment(` | `0x91` @ `02:635B` | `02:6238` copy [confirmed]; `02:4663` engine entered but carry-gated [confirmed] | The branch requires two operands, reads the dimensions at `02:5D98`, and compares the row counts with <code>LD A,H</code><br><code>CP L</code>. Equal rows fall through; `H>L` raises `E_Dimension`. `02:6238` allocates the result and copies the column-major float payload through `02:4539`. The branch then calls `02:4663`. Carry is set at `02:6361` and restored at `02:6378`; `JR C,46EF` at `02:46DC` skips elimination. The statistics regression path enters the same dispatcher through `3A:6398` with carry clear. The `augment(L1,L2)` sibling at `02:637F` also shares the setup at `02:6362` with carry clear. [confirmed] |
| `dim(` (matrix create/set-dims) | `0xB5` @ `62D4` | create + dim setup (`5DBB`/`5DEB`) [confirmed] | The compare at `62D4` is `CP 0xB5`, and `0xB5` = `tDim` (`dim(`), not `randM(` — so this is the `→dim(` matrix create/resize handler. It splits on argument count (`62D9: CP 0x02`): a 2-arg path (`62DD`) and a 1-arg path (`630A`). Both create the result and set its dims through `02:5DBB` (`CALL 5CEB` registers the variable by name, stores the data pointer to `84D3`, reads and zero-rejects the dim bytes <code>OR L</code><br><code>JP Z,2719</code>, stores dims to `84AF`) and `02:5DEB`/`02:631E`. There is no per-cell fill loop here — consistent with `dim(`, which only sets dimensions. `02:5264` (`cplx_swap_dispatch`) is reached only from the `0xBD` complex-operand branch (`62D0`), not here. `randM(` is a separate two-byte token (`tRandM = 0xBB20`) whose decoded fill loop is documented under [The `randM(` cell fill](#the-randm-cell-fill-confirmed). [confirmed] |
| `List►matr(` | `0x8E` @ `61C1` | `02:7D19` + copy | reshapes the argument lists into a matrix (`_DataSize`-counted float copy `4539`/`453F`). [standard] |

The matrix-element kernels these drivers share are `_AdrMEle`/`_AdrMRow` (`4002`/`4000`) for indexing,
`4068` (`mele_store_ckvalid`) for validated stores, and `4539` (`mele_copy9_d3`) for the bulk
column-major payload copy. Each command's dispatch site and body is
[confirmed]. The `randM(` cell fill and the carry-gated role of `02:4663`
inside `augment(` are also [confirmed].

---

## Determinant, inverse, and row reduction [confirmed]

`det(` and `[A]⁻¹` share the Gauss-Jordan elimination engine with partial pivoting —
`matrix_gauss_engine` @ `02:42A6` — the *entry flag in `A`* selecting behaviour; only two
direct call sites exist (byte-verified — `CD A6 42` appears exactly twice). `rref(`/`ref(` are a
separate driver and do not call `42A6` (see below):

| Token / op | site | flag `A` | meaning |
|---|---|---|---|
| `[A]⁻¹` (`^` token `0x0C`, operand = matrix) | `02:5F80` | `0x00` | inverse; singular ⇒ error |
| `det(` (token `0xB3`) | `02:5FC0` | `0x40` | determinant; bit6 set ⇒ singular tolerated (returns 0) |

`det(`'s handler at `02:5FA3` (not a defined function in the disassembly; address
unverified) first type-checks the operand is a matrix (`chk_op_is_matrix` (`02:69B7`):
`type==2 else E_DataType 0x89`), then <code>LD A,0x40</code><br><code>CALL 0x42A6</code>.

### The engine (`42A6`) [confirmed]

```text
matrix_gauss_engine(A = mode flags):
  HL = dims (84AF)
  if H != L -> _JError(0x8C)                # must be square for det/inverse
  if 1x1: handle scalar directly (inverse = _FPRecip)
  461C: scan |all elements| -> max magnitude (pivot-tolerance baseline)
  init permutation/pivot vector at (84D5): perm[k] = k          # identity permutation
  for each pivot column 'col' (84AF loop):
     41D0/41C1: PARTIAL PIVOT — scan the column for the largest |element|,
                compare |OP1| vs |best| via _AbsO1O2Cp
                remember the row
     43B9 -> 414E: SWAP the pivot row into place (full physical row swap)
                4259 swaps the matching entries in the permutation vector,
                and (for det) toggles the running sign
     normalize pivot row: load pivot, _FPRecip / _FPDiv so pivot -> 1
     4473 / 426D: ELIMINATE — for every other row, row_r -= factor * pivot_row
                (4473 = load-load-_FPSub element step, 426D/426F = dot-product /
                 back-substitution accumulate with _FPMult + RST6 _FPAdd)
     accumulate determinant = product of pivots (× sign from swaps)
  SINGULAR handling (43A5): if a pivot is ~0:
        BIT 6,A
        JP Z, 0x26F0 (_ErrSingularMat, E_SingularMat 0x83)
        -> inverse (flag 0, bit6=0) ERRORS
        -> det (flag 0x40, bit6=1) returns 0
```
Key sub-routines (all `page_02`; names are the live Ghidra DB labels): [confirmed]
- `461C` `mat_max_abs` — compute the matrix's max-abs element (numeric scale for the
  near-zero pivot test).
- `41C1` `abs_cmp_op1op2` — `|OP1|` vs `|pivot|` compare (`1A0F`/`1987` abs+compare);
  `41D0` — scan a column for the largest-magnitude pivot (partial pivoting), calling
  `43B9` to swap rows as it goes.
- `43B9` / `414E` `mrow_swap_loop` / `_AdrMRow` — physical row swap / row scale
  (whole-row moves; `414E` loads the `dim0` stride and swaps two whole rows via `_AdrMRow`×2 +
  `1DDA`).
- `4259` — swap two entries in the permutation vector at `84D5`.
- `4473` `ele_sub_ref` — the elimination element step (`[M](i,k) − factor*[M](pivot,k)`:
  <code>RST8</code><br><code>CALL 403C</code><br><code>JP 2297</code> = load + `_FPSub`).
- `426D` `col_dot_accum` / `426F` `col_dot_accum_from` — column dot-product / back-
  substitution accumulate (`_FPMult` + `RST6`).
- Pivot normalize uses `_FPRecip` / `_FPDiv`; sign/inverse use `_InvOP1S`.

`det(` therefore = forward elimination with partial pivoting, return the signed product
of the pivots (each row swap flips the sign); a zero pivot ⇒ `det = 0` (no error).
`[A]⁻¹` = full Gauss-Jordan (reduce to identity, the augmented identity becomes the
inverse); a zero pivot ⇒ `ERR:SINGULAR MAT`.

#### Determinant sign and pivot-product bytes (`02:43D8`–`02:4470`) [confirmed]

The determinant sign comes from the permutation parity, not a separate sign cell. Each
physical row swap (`43B9`) calls `4259` to swap the matching pair in the permutation
vector at `84D5`; the determinant magnitude is the running product of the diagonal pivots
formed during back-elimination. The tail that closes the det/inverse pass:
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
              ; permutation-swap count → conditional _InvOP1S (negate)
43FF (inverse branch): re-walk for the augmented-identity columns,
  4410..446F: per-column back-substitution (4428/445B = _FPMult-accumulate,
              442B/24bd = _InvOP1S sign flips), then JP 0x420F to undo the
              column permutation (4259-pairs) so the inverse comes out in the
              original row/col order.
```
So the sign byte is the LSB of the swap-count applied via `_InvOP1S` (`00:24BD`) at
`43FB`/`442B`; the pivot product is the `238B`/`RST 30h` accumulate over the diagonal in
`43E3-43F6`. The permutation undo (`420F`/`4259`) restores element order for the inverse. [confirmed]

### Separate `rref(` and `ref(` driver [standard]

`rref(`/`ref(` do not re-enter the `42A6` Gauss-Jordan engine. A function-xref shows
`matrix_gauss_engine` (`02:42A6`) has exactly two callers — `mat_inverse_entry` (`02:5F80`,
flag 0) and `det_entry` (`02:5FC0`, flag 0x40); there is no third call site (byte-confirmed
above: `CD A6 42` appears exactly twice). So `det(`/`[A]⁻¹` are the only consumers of that
square-only, partial-pivoting driver. [confirmed]

`rref(` (`BBh,A6h`) and `ref(` (`BBh,A5h`) are 2-byte `0xBB`-lead function tokens. On the
page-38 statement/expression evaluator (`eval_expr_inner` `38:59A4`), token `0xBB` is detected
and `parse_advance` consumes the prefix; the second byte is then dispatched through the
evaluator's six-entry `leaf_production_handler_table` at `38:7175`.
The selector at `38:701A`–`7026` chooses `grammar_handler_table`, the
`38:478C` code family, or this leaf table; `703A: CALL 0x0033` = `_LdHLind`
jumps to the resolved handler. Their reduced-row-echelon elimination is therefore a distinct,
non-square-tolerant driver reached through that table — a separate routine from `42A6`, using
the same per-element FP primitives (`_FPDiv`/`_FPMult`/`_FPSub`) but with its own pivot loop
that tolerates rectangular matrices and rank deficiency (zero rows left in place, no
`SINGULAR MAT`). The concrete rref/ref body sits behind the two-byte entries in
`leaf_production_handler_table`; the table is now named and typed in the rebuilt
database, but the two tokens' exact handler selection has not yet been isolated.
The two-caller xref establishes that it is a
separate driver from `02:42A6` [confirmed]. Its exact body address remains
[standard].

---

## Floating-point and VAT integration [confirmed]

- Every element is a `TIFloat` ([Floating-point](floating-point.md)). Indexing produces a *pointer*; the value is then
  moved into `OP1`/`OP2` (`RST4` = load-9, `_Mov9B`, `_MovFrOP1`) and all arithmetic is the FP
  engine's `RST 30h`(`_FPAdd`)/`_FPMult`/`_FPDiv`/`_FPSub`/`_FPRecip`. There is no SIMD; a
  matrix multiply makes thousands of these calls. Complex elements (lists/`[i]`) carry a
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
| `00:1115` | `_CreateRMat` | new matrix (`H*L*9+2`, header `dim0,dim1`) [confirmed] |
| `00:1EF6` | `_HTimesL` | element count = H*L (dims multiplied) [confirmed] |
| `00:1930` | `_HLTimes9` | ×9 (real `TIFloat` stride) [confirmed] |
| `02:4000` | `_AdrMRow` | address of matrix column start (column stride) [confirmed] |
| `02:4002` | `_AdrMEle` | matrix element address: `((column-1)*dim0+(row-1))*9` [confirmed] |
| `02:4044` | `_GetMToOP1` | `[M](i,j)` → OP1 [confirmed] |
| `02:406C` | `_PutToMat` | OP1 → `[M](i,j)` (validated) [confirmed] |
| `02:40BA` | matrix-multiply body | O(n³) triple loop, decoded from `rom.bin` (not a defined function in the disassembly); called from `02:5FFF`/`4605`/`5B39`. `0x40BA` in ti83plus.inc is the unrelated `_SinCosRad` bcall ID. [confirmed] |
| `02:4108` | `identity_build` | `identity(n)`: diagonal-1 fill (token 0xB4) [confirmed] |
| `02:412A` | `mat_transpose` | transpose `[A]ᵀ` body (token `0x0E`, dispatched `60E9`/called `60FE`): per-cell copy `dst(c,r)=src(r,c)` via the swapped dest header [confirmed] |
| `02:414E` | `mrow_swap_loop` | row swap/scale (elimination) [confirmed] |
| `02:4178` | `mat_fill_type1` | live DB name; single-counter per-cell fill/apply loop in the `414A`–`4178` block — not transpose [confirmed] |
| `02:4539` | `mele_copy9_d3` | bulk column-major float-payload copy (skip 2 dim bytes, `LDIR`); used by `augment(`/reshape [confirmed] |
| `02:4663` | `mat_gauss_engine` | live DB name; `min(H,L)` partial-pivoting elimination engine; only caller is the `augment(` `0x91` branch (`6379`). Its role inside plain `augment(` is the one open item [standard] |
| `02:4773` | `mat_to_list_cols` | `Matr►list(` 2-arg column-extract engine (only caller `63A0`): nested col×row walk copying matrix columns into list element(s) [confirmed] |
| `02:5264` | `cplx_swap_dispatch` | live DB name; complex OP-pair arrange/swap (`5344`/`52D3`) reached only from the `0xBD` branch (`62D0`) — not the `0xB5`/`dim(` matrix-create branch [confirmed] |
| `02:6238` | `mat_augment_copy` | `augment(` column-concat: allocate result (`5DE0`) + `4539` payload copy + re-point `84D3` [confirmed] |
| `02:49E3` | `lele_copy_until_eq` | live DB name; list-element copy-until-length-match (`21BB`, `RET Z`); inner copy of the `Matr►list(` 1-arg/list path (`6397`) [confirmed] |
| `02:41C1` | `abs_cmp_op1op2` | absolute-value compare: OP1 vs pivot [confirmed] |
| `02:41D0` | `pivot_col_scan` | partial-pivot: find largest absolute value in column [confirmed] |
| `02:4259` | `perm_swap` | swap two entries of the permutation vector (84D5) [confirmed] |
| `02:426D`/`426F` | `col_dot_accum`/`col_dot_accum_from` | column dot-product / back-substitution accumulate [confirmed] |
| `02:42A6` | `matrix_gauss_engine` | inverse(flag 0)/det(flag 0x40) Gauss-Jordan + partial pivot; square-only (`H==L` guard) [confirmed] |
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
| `ram:21C4` | `chk_type_lt_1a` | classify element type width: <code>AND 0x1F</code><br><code>CP 0x1A</code><br><code>CP 0x18</code><br><code>CCF</code> — real-vs-complex (0x0C) element width [confirmed] |
| `35:79E9` | `list_idx_times9` | list index ×9 + dispatch [confirmed] |
| `07:4D3B` | `_RedimMat` | re-dimension matrix/list [confirmed] |
| `07:4F07` | `_InsertList`/`_IncLstSize` | grow a list in place [confirmed] |
| `07:4F43` | `_DelListEl` | delete list element(s) [confirmed] |
| `38:6C8F` | `_StMatEl` | parser store into `[M](r,c)` (bounds-checked) [confirmed] |
| `38:741F`/`7422` | `_ConvDim`/`_ConvDim00` | coerce a dim/index to real [confirmed] |
| `00:26F0` | `_ErrSingularMat` | `E_SingularMat 0x83` [confirmed] |
| `00:26F8` | `_ErrIncrement` | `E_Increment 0x85` [confirmed] |
| `00:2715` | `_ErrDimMismatch` | `E_DimMismatch 0x8B` [confirmed] |
| `00:2719` | `_ErrDimension` | `E_Dimension 0x8C` [confirmed] |

---

## Resolved behavior and remaining questions

- `rref(`/`ref(` use a separate driver, not `42A6`. Xref proves `42A6` has
  exactly two callers (inverse `5F80`, det `5FC0`); rref/ref are 2-byte `0xBB`-lead function
  tokens dispatched via the page-38 evaluator's
  `leaf_production_handler_table` (`38:7175`). The `ref(` execution dispatch is
  byte-pinned in the page `02` command chain. It compares `CP 0x2D` at `02:609A`
  and, with arguments present, executes <code>RST 28h</code><br><code>.dw 0x4B85</code>. Bcall ID `4B85h`
  resolves through the page `3B` table to `35:7995`; its port-encoded page byte
  `0x75` selects page `35`.
  `35:7995` is an iterative FP reduction loop (`_Minus1`/`_FPMult`/OP-exchange primitives,
  back edge at `35:79C4`) consistent with the row-reduction driver. [confirmed]
  The `rref(` execution dispatch lives on page `38`, where two entry stubs
  (`38:514F` with carry set and `B=1`; `38:5157` with carry clear and `B=0`) converge on
  <code>RST 28h</code><br><code>.dw 0x4B88</code> at `38:515D`. The ID resolves through the page `3B` table to
  `02:7C23`, a per-element driver that walks the pushed matrix data from the FPS pointer
  (`LD HL,(9824)` then a `DJNZ` loop), validates dimensions against the header bytes
  (`8479`/`847A` exponent checks raising through `26F4` on failure), and stores results back
  per cell. No `CP 0x2E` site exists on page `02`, so the parser normalizes the `rref(` token
  before this dispatcher. The role of `B` and carry in distinguishing `rref(` from related
  calls remains [hypothesis]. The parse-side signature descriptors remain distinct (`38:431E`/`0x5108` for
  `ref(` vs `38:4323`/`0x510C` for `rref(`).
- det sign / pivot-product (`42A6` tail `43D8-4470`) and dim labelling. The det
  sign = LSB of the permutation-swap count applied via `_InvOP1S` (`24BD`) at `43FB`/`442B`;
  the magnitude is the `238B`/`RST 30h` diagonal-pivot accumulate (`43E3-43F6`); `420F`/`4259`
  undo the column permutation for the inverse. Row/col vs dim0/dim1 is now [confirmed]:
  `dim0` (first header byte) = #rows, and `_AdrMEle` takes `B=column`, `C=row`; see [Data layouts](#data-layouts-and-creator-routines-confirmed) and [Element access](#element-access-and-index-to-offset-conversion-confirmed).
- transpose, `Matr►list(`, and the `augment(` column-concat bodies. Each command's
  page-`02` dispatch site and body are byte-confirmed, every body having exactly one caller:
  - transpose `[A]ᵀ` (token `0x0E` @ `60E9`) → `02:412A` (only caller `60FE`): the dim header is
    swapped (`60F5`) and `412A` copies `dst(c,r)=src(r,c)` over every cell. `02:4178` is a separate
    single-counter fill/apply, not transpose. [confirmed]
  - `Matr►list(` (`0x8D` @ `6388`) → `02:4773` (2-arg column-extract engine, only caller `63A0`)
    with `02:49E3` as the 1-arg/list inner copy. [confirmed]
  - `augment(` (`0x91` @ `635B`) → equal-rows guard (<code>CP L</code><br><code>JP NC,2719</code>) + column-concat copy at
    `02:6238` (`5DE0` allocate + `02:4539` `LDIR` payload copy). [confirmed]
  - `dim(` (`0xB5` @ `62D4`; `0xB5` = `tDim`, not `randM(`) → creates the result and sets its
    dims (`5DBB`/`5DEB`). `02:5264` (`cplx_swap_dispatch`, only caller `62D0` in the `0xBD` branch)
    is reached only from that complex branch, not here. [confirmed]
  - `List►matr(` `0x8E` branch (`61C1`) → `02:7D19` + `_DataSize` copy (`4539`/`453F`) is
    unchanged [standard].
- The `augment(` call to `02:4663` performs pivot-column setup but skips elimination because
  the engine tests the carry set by `02:6361`. The statistics regression path enters the same
  dispatcher with carry clear. [confirmed]
- The `randM(` fill loop at `02:5CC1`–`02:5CE6` computes
  $\operatorname{int}(19 \cdot \operatorname{rand}) - 9$ per cell. It calls `_Random`
  (`36:7DC9`) through the page 0 banked-call stub at `ram:392D`; no `RST 28h` bcall site is
  involved. See [The `randM(` cell fill](#the-randm-cell-fill-confirmed). [confirmed]
- `seq(`/`SortA(`/`SortD(`/stats list-builders: confirm the collect-then-`_CreateRList` loop
  and the in-place float sort/compare. (Residual — comparator `_CpOP1OP2` confirmed; the
  unanalyzed page-02 sort body's element-load is still not byte-traced.)
