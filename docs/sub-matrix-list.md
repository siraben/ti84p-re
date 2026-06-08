# Matrices & lists

*TI-84 Plus OS 2.55MP — feature deep dive.*

How the TI-84 Plus OS (2.55MP) stores, indexes, and computes on lists and
matrices — the routines a college student hits doing linear algebra (`det(`, `[A]⁻¹`,
`rref(`, `[A]*[B]`, `identity(`, `T`) and data work (`L1+L2`, `dim(`, `sum(`, `seq(`,
`SortA(`). Companion to [05-variables-vat.md](05-variables-vat.md) (where the data lives), [06-floating-point.md](06-floating-point.md)
(how each element is computed), and [sub-vat-archive.md](sub-vat-archive.md) (Store/Recall/Archive).

All `page:addr` are read from the raw Z80 disassembly, not the decompiler alone.
Page numbers are the masked flash page (`rawpage & 0x3F`). The whole-OS image lives in one
Ghidra program with address spaces `ram` (the page-0/RAM-resident 0x0000–0x7FFF window) and
`page_NN` for each flash page mapped into the 0x4000–0x7FFF bank-A window.

Confidence (this doc's shorthand; see [Conventions](conventions.md)): [C]=confirmed from disassembly (≈`[confirmed]`), [H]=high (structure clear, light inference) (≈`[standard]`), [I]=inferred / standard documented TI behaviour (≈`[hypothesis]`).

---

## 0. TL;DR — the mental model

- A list is `word count` (2 bytes) followed by `count` × 9-byte `TIFloat` elements
  (18-byte complex elements if the list is complex, flagged `0x0C`). Element $i$ (1-based)
  lives at $\mathrm{addr}(L_i)=\mathrm{data}+2+(i-1)\cdot 9$.
- A matrix is `byte dim0; byte dim1;` (two 1-byte dimensions) followed by
  `dim0*dim1` × 9-byte `TIFloat`, stored column-major. The element offset from the start
  of the data area (after the 2 dim bytes) is

  $$\mathrm{offset}=\big((\mathit{idx}_0-1)\cdot \mathit{dim}_0+(\mathit{idx}_1-1)\big)\times 9$$
- Every element read/write routes one `TIFloat` through `OP1`/`OP2` and the FP engine —
  there is no "vector unit"; matrix multiply is a triple loop of `_FPMult`+`_FPAdd`.
- The data area is found through the VAT (`_FindSym`, [doc 05](05-variables-vat.md)): the VAT entry's data
  pointer + page byte locate the `count`/`dim` header, after which all indexing is pointer
  arithmetic computed by `_AdrLEle`/`_AdrMEle`.
- One shared Gauss-Jordan engine (`page_02:42A6`) implements matrix inverse `[A]⁻¹`
  (flag `0x00`) and `det(` (flag `0x40`) with partial pivoting. `rref(`/`ref(` are
  the same elimination family.

---

## 1. Data layouts & the creator routines [C]

### List — `_CreateRList` (`00:10C4`), `_CreateCList` (`00:1109`)
```
_CreateRList(count, dataPtrOut):
  reject unless OP1 name token (8478.exp) ∈ {0x5D, 0x24, 0x3A, 0x72}  ; list-name classes
  var_alloc(1)                  ; carve  count*9 + 2  bytes via _InsertMem
  store count word at data[0..1]
  if list is complex (8499.type & 8): data[2] = 0x0C   ; element-size flag
```
Layout: `[countLo countHi] [TIFloat e1] [TIFloat e2] …`. A complex list keeps a `0x0C`
flag and 18-byte elements.

### Matrix — `_CreateRMat` (`00:1115`)
```
_CreateRMat(dimWord, dataPtrOut):
  _HTimesL()                    ; element count = H * L  (the two dims multiplied)
  var_alloc(2)                  ; carve  H*L*9 + 2  bytes
  header: LD (HL),C ; INC HL ; LD (HL),B   ; writes dim0 then dim1
```
- `_HTimesL` (`00:1EF6`) is literally `result = H * L` (`B=H; HL=Σ L`, a `DJNZ` add loop) —
  it computes the element count from the two dimension bytes. [C]
- Header = two bytes `dim0,dim1`; data is `dim0*dim1` floats column-major.

> **Dimension naming [C].** Settled by disassembly. `_AdrMEle` (`02:4002`) reads the header's
> first byte (`LD A,(DE); LD L,A`) and uses it as the major stride, looping `(B−1)`
> adds of it and then `+(C−1)` *within* a column (column-major). The major stride of a
> column-major array is the number of rows, so the first header byte (`dim0`) = #rows,
> and `_AdrMEle`'s `B = idx0 = column`, `C = idx1 = row`. `_CreateRMat` (`ram:1115`) confirms
> the layout: it is `PUSH HL ; CALL _HTimesL (1EF6) ; LD A,2 ; JR 10DD` — `_HTimesL` returns
> `H·L` (the element count) and `A=2` is the 2-byte dim header; the two dimension bytes are
> stored `dim0` (rows) then `dim1` (cols). The byte-confirmed index arithmetic
> `((idx0−1)·dim0 + (idx1−1))·9` is therefore a (column, row) register convention with a row-count stride.

---

## 2. Element access — the index→offset math [C]

This is the heart of everything. Two address-calculators turn a 1-based index into a byte
pointer, then a 9-byte move shuttles the `TIFloat` to/from `OP1`.

### List element address — `_AdrLEle` (`02:47C5`)
```z80
_AdrLEle(index, listDataPtr):           ; HL=index, DE=listDataPtr
  INC DE ; INC DE                        ; skip the 2-byte count header
  A = (DE) & 0x1F                         ; element type (low 5 bits); 0x0C ⇒ complex
  CALL 21C4                               ; classify real vs complex element width
  HL = (index − 1)                        ; _HLTimes9(index-1)
  CALL 1930  (_HLTimes9)                  ; HL = (index-1) * 9
  HL += DE                                ; final element pointer
```
So list element *i* is at `data + 2 + (i−1)*9` (×18 path for complex). `_HLTimes9`
(`00:1930`) is the universal "multiply by 9" (real `TIFloat` size). `chk_type_lt_1a` (`ram:21C4`)
masks the type to ≤0x19 and sets carry for the complex case (drives the 18-byte width). [C]

Convenience wrappers (all = `_AdrLEle` then a 9-byte move through OP1, complex-aware): [C]
- `_GetLToOP1` (`02:47EA`) — list[i] → OP1 (real or complex via two `_Mov9B`).
- `_RclListElemToOP1` (`02:47FB`), `_RclListElemB` (`02:47FE`) — recall to OP1 with the
  index pre-loaded in RAM (`84AF`/`84D3`).
- `_PutToL` (`02:4829`) — OP1 → list[i]; `_CkValidNum` validates the float first, then
  copies, honoring the complex (`& 0xC`) element width.
- `_RclCListElem` (`02:49A7`), `_RclCListElemB` (`02:49B5`) — complex-list element via
  `_CplxOPArrange` (splits real/imag into OP1/OP2).
- `_GetPosListElem` (`02:5BBB`) — fetch by a *positive-integer* index with `_CkOP1Pos`
  bounds (loads `A=0x15` = `E_Stat` and jumps to the error vector `ram:2741` on a bad index).

### Matrix element address — `_AdrMEle` (`02:4002`) [C]
```z80
_AdrMEle:                                 ; B=column idx0, C=row idx1, DE=matrixDataPtr
  if B==0 or C==0 -> LD A,0x78 ; JP 0x2793 ; 0-index rejected (error vector)
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
is the column index and `C=idx1` is the row index — see the [C] dimension-naming note in §1. [C]

Matrix element wrappers: [C]
- `_AdrMRow` (`02:4000`) — address of the *start of column idx0* in the column-major buffer
  (loops `(idx0−1)` × dim0, no `+(idx1-1)`); whole-row operations layer their own iteration on top.
- `_GetMToOP1` (`02:4044`) — `[M](r,c)` → OP1 (`_AdrMEle` then `RST4` = load 9 bytes).
- `_PutToMat` (`02:406C`) = `mele_store_ckvalid` (`02:4068`): `_AdrMEle ; _CkValidNum ; _MovFrOP1` — OP1 →
  `[M](r,c)` with validation.
- `_StMatEl` (`38:6C8F`) — high-level "store into `[M](r,c)`" used by the parser: resolves
  the matrix name (`5F45`), bounds-checks indices against the dims (`r≤rows && c≤cols`, else
  `_JError 0x8C` = `E_Dimension`), unarchives if needed, then `_PutToMat`. [C/H]

### Internal index helpers reused by the algorithms [C]
- `mele_adr_af_jp` (`02:403C`) = `_AdrMEle(currentIJ) ; RST4` — "load `[M](i,j)` to OP1" (the elimination
  inner-loop read). Indices come from the loop state at `84AF/84B3/84B4`.
- `mele_adr_to8483` (`02:4051`) = `_AdrMEle ; _Mov9B(→OP2@8483)` — load element to OP2.
- `mele_put_af` (`02:405A`) / `mele_put_d3` (`02:405E`) = `_AdrMEle ; _CkValidNum ; _MovFrOP1` — store OP1 back to `[M](i,j)`.
- `_ListIdxTimes9` (`35:79E9`) = `_HLTimes9(idx)` then a small dispatch (`RST4`) — the list
  analogue used in a few list-builder paths.

---

## 3. List operations [C/H]

### Create / resize / insert / delete
| Routine | addr | Role |
|---|---|---|
| `_CreateRList` | `00:10C4` | new real list: `count*9+2` bytes (§1) [C] |
| `_CreateCList` | `00:1109` | new complex list: `count*18+2` [C] |
| `_IncLstSize` | `07:4EF4` | grow a list in place via `_InsertMem`; caps length at 999 (`0x3E7`), else `E_Dimension 0x8C` (`07:4F00 JP Z,0x2719 → LD A,0x8C`). `_InsertList` is the distinct sibling at `07:4F07`. [C] |
| `_DelListEl` | `07:4F43` | delete element(s): `_HLTimes9(index)` to size the gap (×2 if complex, `& 0x1F == 0x0D`), then `_DelMem` via a cross-page jump [C] |
| `_RedimMat`/`_ConvDim` | `07:4D3B` / `38:741F` | re-dimension (shared with matrices); `_ConvDim`/`_ConvDim00` (`38:741F/7422`) coerce OP1 to a real index first [C] |

### `dim(`, `dim(L)→n`, list↔value
`dim(` reads the `count` word straight from the list header; assigning `n→dim(L)` calls the
resize path (`_IncLstSize`/`_DelListEl`) to grow/shrink, zero-filling new cells. List→matrix
and matrix→list (`List►matr(`, `Matr►list(`) reshape via `_DataSize` + a column-major copy
(`mele_copy9_d3` (`02:4539`)/`mele_copy9_loop` (`02:453F`), a `_DataSize`-counted byte copy of the float payload). [H]

### List arithmetic `L1+L2`, scalar broadcast
Binary list ops are element-wise folds: the parser walks both lists by index, loads
`L1[i]`→OP1, `L2[i]`→OP2, applies the FP RST shortcut (`RST 30h _FPAdd`, `_FPSub`, `_FPMult`,
`_FPDiv`), stores into a freshly `_CreateRList`'d result. Length mismatch ⇒ `E_DimMismatch`
(`_ErrDimMismatch 00:2715`, `0x8B`); a list⊕scalar broadcasts the scalar across every element.
[H — the per-element FP path is confirmed; the outer driver is the parser's binary-op handler.]

### `sum(`, `prod(` — higher-order folds over a list [C]
Tokens `0xB6`=`sum(`, `0xB7`=`prod(` load a *combiner function pointer* and fold the
list (dispatcher `02:6104`):
```
sum(  : HL = 0x3A83 (cross-page → FP add-accumulate),  seed via _OP1Set0
prod( : HL = 0x49B9 (seed accumulator = 1.0, _PushOP1), combine with _FPMult
        CALL 0x64B7 ; ... ; JP (HL)   ; apply the combiner across e1..eN
```
The fold seeds the accumulator (0 for sum, 1 for prod), then for each element does
`acc = combine(acc, L[i])` through OP1/OP2. Works on real and complex lists (`type 1`/`0xD`
both route to `02:6140`). [C]

### `seq(`, `cumSum(`, `SortA(`/`SortD(`, `mean(`/`median(`/`stdDev(` [H/I]
- `seq(expr,var,lo,hi[,step])` evaluates `expr` for `var = lo..hi`, pushing each result
  and finally `_CreateRList`-ing the collected floats (the generic list-builder loop;
  `_SetSeqM 36:7D1F` is the sequence-graph variant). [H]
- `cumSum(` is a running `_FPAdd` writing back each partial sum (the sum-fold with the
  accumulator stored every step). [I]
- `SortA(`/`SortD(` — list sort in place (`SortA(` co-sorts dependent lists); the comparator
  and per-element sort key are detailed in the next subsection. [confirmed comparator]
- Stats (`mean/median/sum/stdDev/variance`) are list folds layered on `sum(`/sort. [I]

### `SortA(` / `SortD(` — list sort [confirmed comparator]

`SortA(` (`tSortA` `0xE3`) and `SortD(` (`tSortD` `0xE4`) sort a list in place — ascending and
descending respectively; `SortA(L1,L2,…)` co-sorts the trailing lists by the same permutation. This
is the command sort, distinct from the stat-internal `stat_sort` (`3A:7935`) that backs median/
quartile/Med-Med (see [Statistics](sub-statistics.md)).

The sort body is on page `0x02` (around `02:5939`); it is reached only through the parser's
computed command dispatch, so Ghidra leaves it as unnamed code. Its comparator is `_CpOP1OP2`
(`00:198D`), confirmed by the call at `02:5939`.

`_CpOP1OP2` compares two `TIFloat`s as real numbers [confirmed from disassembly]: it tests the
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
`list_fold_dispatch` (`02:6104`) plus the page-38 list parse/store helpers.
[dynamic run confirmed; list primitives above are confirmed where marked]

---

## 4. Matrix operations [C]

### `dim(`, redim, identity, copy
- `dim([M])` reads the two header bytes → a 2-element list `{rows,cols}`; `{r,c}→dim([M])`
  reallocates via `_RedimMat` (`07:4D3B`), preserving overlapping cells and zero-filling new
  ones. [C/H]
- `identity(n)` (token `0xB4` → `identity_build` (`02:4108`)) [C]: allocate `n×n`, then walk every cell
  writing `1.0` when `row==col` (the `exp==type` test) and `0` otherwise:
  ```
  _OP1Set1 ; for each (i,j): if i==j -> store 1.0 (mantissa[0]=0x10) else 0
  ```
- `Fill(value,[M])` / `randM(` stamp a constant / random values across all cells via a
  per-cell loop over the whole matrix. The `02:62D4` branch (`CP 0xB5`) is `dim(` (`0xB5` =
  `tDim`), which creates the `r×c` result (`5DBB` → `_CreateRMat 110F`) and stores the dims
  (`631B`/`631C`/`4825`) but performs no fill. `randM(` itself is a separate 2-byte token
  (`tRandM` = `0x20`, `0xBB`-prefix group); its per-cell random fill is the one residual still
  open (§4) — and notably it does *not* use the `_Random` bcall (`0x4B79`): a ROM-wide scan finds
  zero `RST 28h; .dw 0x4B79` sites, so randM's randomness comes from some other path. [H]
- Matrix copy/reshape = `_DataSize`-counted byte copy of the float payload
  (`mele_copy9_d3` (`02:4539`)/`mele_copy9_loop` (`02:453F`)). [C]

### `[A] + [B]`, `[A] - [B]`, scalar·[A] — element-wise [H]
Binary matrix add/sub apply the FP op per cell with a nested `for col { for row { load [M](r,c)→OP1;
op; store } }` walk and require equal dims (`_ErrDimMismatch 0x8B`). The nested two-counter cell
walk at `02:412A` is the transpose copy (§ transpose); the add/sub element-loop driver is a
sibling in the same `412A`–`414E` family and is inferred here. [H]

### `[A] * [B]` — matrix multiply [C]
The multiply body is at `02:40BA`. It is not a defined function in the live Ghidra DB (so the
decompiler/MCP can't reach it), so this was decoded from `rom.bin` directly with `z80dasm`,
cross-checked against a routine Ghidra *does* define. The body is called from `02:5FFF` (the
`*` operator handler, in the `02:5FE6` region) and reused from `02:4605` and `02:5B39`. (`0x40BA`
is also the `_SinCosRad` bcall ID in ti83plus.inc — a hex coincidence, unrelated to this page-02
address.)

`40BA` is a classic O(n³) triple loop with an FP accumulator:
```
for each result cell (i,j):                  ; counters at 84B7, 84B4
    for k = 1 .. inner:                       ; inner counter at 84AF
        load [A](i,k)          (403C mele_adr_af_jp)
        multiply by [B](k,j)   (47B9 / 0166F  FP multiply)
        accumulate             (479F)
    store acc -> [C](i,j)      (4064 / 405A)
```
The three `dec (hl)` counters (`84AF` inner, `84B4`, `84B7`) each have a `jr nz` back-edge
(`40E5`, `40F9`, `4100`); an inner-dim mismatch (`A.cols ≠ B.rows`) raises `_ErrDimMismatch`. An
`n×n` product is `n³` `TIFloat` multiply+add steps. [C — body decoded from `rom.bin`; callers
`02:5FFF`/`4605`/`5B39` byte-verified]

### Transpose `[A]ᵀ` — `02:412A`, dispatched from the `ᵀ` token `0x0E` [C]
The transpose operator `ᵀ` is the postfix token `tTrnspos` = `0x0E`. The page-02 command
dispatcher handles it at `02:60E9` (`CP 0x0E`): it requires one matrix operand (`CP 0x02 ;
JR NZ`), swaps the two dimension bytes for the result header (`60F5: LD A,H ; LD H,L ; LD L,A`),
allocates the transposed-shape matrix (`5DBB`/`5DE0`), runs the per-cell copy body at `02:412A`,
then stores via `JP 0x5F89`. `02:412A` has exactly one caller, `02:60FE` (byte-verified `CD 2A 41`).

`02:412A` is the transpose copy [C]. It walks every source cell and writes the value into the
destination whose `_AdrMEle` stride is the *swapped* dimension, so `dst(c,r) = src(r,c)`:
```z80
412A: LD HL,(84AF)              ; loop counters = dims
412E: CALL 403C                 ; load src [M] (B=col,C=row) from (84D3) → OP1
4131: LD HL,(84AF) ; LD B,L ; LD C,H
4136: CALL 4068                 ; store OP1 → dst [M] via dest ptr (84D7)
4139: DEC (84AF) ; JR NZ,412E   ; inner counter
4141: LD (HL),C ; INC HL ; DEC (HL) ; JR NZ,412E  ; outer counter
4146: POP HL ; LD B,L ; LD C,H ; RET
```
`403C` reads from the source data pointer `(84D3)`; `4068` writes to the destination pointer
`(84D7)`. Because the destination header carries the dims swapped (the `60F5` swap), `_AdrMEle`
(`4002`) computes the column-major offset with the row/column roles exchanged, so the same linear
walk lands element `src(r,c)` at `dst(c,r)` — a true transpose, which re-indexes *both* `i` and
`j`. [C]

`02:4178` (`mat_fill_type1`) is a separate single-counter fill/apply in the `414A`–`4178` block,
*not* the transpose body. [C]

### `augment(`, `dim(`, `List►matr(`, `Matr►list(` — per-function drivers [C/H]
These are dispatched from the page-02 function-token evaluator (`list_fold_dispatch`, the
`CP imm ; JR/JP` chain that runs `5E46`/`60C8`–`63xx`, keyed on the token byte). Each command's
body and its single caller are byte-verified below.

| Command | dispatch site | body | what the disassembly shows |
|---|---|---|---|
| `Matr►list(` | `0x8D` @ `6388` | `02:4773` (2-arg), `02:49E3` (1-arg list copy) | [C] The `0x8D` branch splits on argument count (`638D: CP 0x02`). The column-extract engine is `02:4773` (2-arg path: `639D: CALL 5DD8 ; CALL 4773`; only caller `63A0`, byte-verified `CD 73 47`): it nests a per-row loop (`477B: LD B,1 …`, reading via `4040` `_AdrMRow`/`4068` `mele_store_ckvalid`) inside a column loop over `(84AF)`, copying matrix columns into list element(s) (`4051`/`479F`). The 1-arg/list path uses `02:49E3` (`6397: CALL 0x49E3`), a list-element copy-until-length-match (`47E6` recall, `4825` store, `21BB` compare vs `(84AF)`, `RET Z`). |
| transpose `ᵀ` | `0x0E` @ `60E9` | `02:412A` | [C] Swaps the dim header (`60F5`), allocates the transposed shape, then `412A` copies `dst(c,r)=src(r,c)` over every cell (`403C` read from `(84D3)`, `4068` write to `(84D7)`); only caller `60FE`. See the transpose subsection above. |
| `augment(` | `0x91` @ `635B` | `02:6238` copy [C]; `02:4663` engine [H] | The `0x91` branch requires two operands (`CP 0x02`), reads the dims (`5D98`), and checks the two row counts with `LD A,H ; CP L`: equal rows fall through (`JR Z`) and `H>L` raises `E_Dimension` (`JP NC,2719`). It then runs the column-concatenation copy at `02:6238` [C]: `6238` allocates the result (`5DE0` → `5DE6` → `_CreateRMat 110F`) and bulk-copies the float payload with `02:4539` (`mele_copy9_d3` — skip the 2 dim bytes, `LDIR` the column-major data), re-pointing `84D3←84D7`. The branch then calls `02:4663` (`6379`, only caller; byte-verified `CD 63 46`), a partial-pivoting elimination engine: it computes `min(H,L)` (`4672: LD A,H ; CP L ; JR C ; LD L,H`), inits via `475E`, and iterates from `BC=0x0101` calling `461C` (max-abs), `41D0` (pivot-column scan), `198D` (compare), `471C` (permutation swap) and `405E` (store). The column-concat copy (`6238`/`4539`) is confirmed augment behaviour [C]; `4663`'s elimination pass on the concatenated result is byte-confirmed but its role for plain `augment(` is left open [H]. (`augment(L1,L2)` list-concat is the `0x92` sibling at `637F`, sharing the `6362` setup.) |
| `dim(` (matrix create/set-dims) | `0xB5` @ `62D4` | create + dim setup (`5DBB`/`5DEB`) [C] | The compare at `62D4` is `CP 0xB5`, and `0xB5` = `tDim` (`dim(`), not `randM(` — so this is the `→dim(` matrix create/resize handler. It splits on argument count (`62D9: CP 0x02`): a 2-arg path (`62DD`) and a 1-arg path (`630A`). Both create the result and set its dims through `02:5DBB` (`CALL 5CEB` registers the variable by name, stores the data pointer to `84D3`, reads and zero-rejects the dim bytes `OR L ; JP Z,2719`, stores dims to `84AF`) and `02:5DEB`/`02:631E`. There is no per-cell fill loop here — consistent with `dim(`, which only sets dimensions. `02:5264` (`cplx_swap_dispatch`) is reached only from the `0xBD` complex-operand branch (`62D0`), not here. `randM(` is a separate 2-byte token (`tRandM` = `0x20`, `0xBB`-prefix group) routed through the `0xBB` dispatcher; its cell-fill body is unidentified — it uses no `_Random` bcall (`0x4B79`: a ROM-wide scan finds no `RST 28h; .dw 0x4B79` site). [H] |
| `List►matr(` | `0x8E` @ `61C1` | `02:7D19` + copy | reshapes the argument lists into a matrix (`_DataSize`-counted float copy `4539`/`453F`). [H] |

The matrix-element kernels these drivers share are `_AdrMEle`/`_AdrMRow` (`4002`/`4000`) for indexing,
`4068` (`mele_store_ckvalid`) for validated stores, and `4539` (`mele_copy9_d3`) for the bulk
column-major payload copy. Each command's dispatch site and body are byte-confirmed above; the
single residual is `randM(`'s per-cell fill and `4663`'s elimination role inside `augment(`. [C for
the bodies; H for those two residuals]

---

## 5. The heavy ones — `det(`, `[A]⁻¹`, `rref(` / `ref(` [C]

`det(` and `[A]⁻¹` share the Gauss-Jordan elimination engine with partial pivoting —
`matrix_gauss_engine` @ `page_02:42A6` — the *entry flag in `A`* selecting behaviour; only two
direct call sites exist (byte-verified — `CD A6 42` appears exactly twice). `rref(`/`ref(` are a
separate driver and do not call `42A6` (see below):

| Token / op | site | flag `A` | meaning |
|---|---|---|---|
| `[A]⁻¹` (`^` token `0x0C`, operand = matrix) | `02:5F80` | `0x00` | inverse; singular ⇒ error |
| `det(` (token `0xB3`) | `02:5FC0` | `0x40` | determinant; bit6 set ⇒ singular tolerated (returns 0) |

`det(`'s handler at `02:5FA3` (not a defined function in the current Ghidra DB; address
unverified) first type-checks the operand is a matrix (`chk_op_is_matrix` (`02:69B7`):
`type==2 else E_DataType 0x89`), then `LD A,0x40 ; CALL 0x42A6`.

### The engine (`42A6`) [C]
```
matrix_gauss_engine(A = mode flags):
  HL = dims (84AF); if H != L -> _JError(0x8C)   ; must be square (det/inverse)
  if 1x1: handle scalar directly (inverse = _FPRecip)
  461C: scan |all elements| -> max magnitude (pivot-tolerance baseline)
  init permutation/pivot vector at (84D5): perm[k] = k          ; identity permutation
  for each pivot column 'col' (84AF loop):
     41D0/41C1: PARTIAL PIVOT — scan the column for the largest |element|,
                comparing |OP1| vs |best| via _AbsO1O2Cp; remember the row
     43B9 -> 414E: SWAP the pivot row into place (full physical row swap);
                4259 swaps the matching entries in the permutation vector,
                and (for det) toggles the running sign
     normalize pivot row: load pivot, _FPRecip / _FPDiv so pivot -> 1
     4473 / 426D: ELIMINATE — for every other row, row_r -= factor * pivot_row
                (4473 = load-load-_FPSub element step; 426D/426F = dot-product /
                 back-substitution accumulate with _FPMult + RST6 _FPAdd)
     accumulate determinant = product of pivots (× sign from swaps)
  SINGULAR handling (43A5): if a pivot is ~0:
        BIT 6,A ; JP Z, 0x26F0 (_ErrSingularMat, E_SingularMat 0x83)
        -> inverse (flag 0, bit6=0) ERRORS;  det (flag 0x40, bit6=1) returns 0
```
Key sub-routines (all `page_02`; names are the live Ghidra DB labels): [C]
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
  `RST8 ; CALL 403C ; JP 2297` = load + `_FPSub`).
- `426D` `col_dot_accum` / `426F` `col_dot_accum_from` — column dot-product / back-
  substitution accumulate (`_FPMult` + `RST6`).
- Pivot normalize uses `_FPRecip` / `_FPDiv`; sign/inverse use `_InvOP1S`.

`det(` therefore = forward elimination with partial pivoting, return the signed product
of the pivots (each row swap flips the sign); a zero pivot ⇒ `det = 0` (no error).
`[A]⁻¹` = full Gauss-Jordan (reduce to identity, the augmented identity becomes the
inverse); a zero pivot ⇒ `ERR:SINGULAR MAT`.

#### Det sign / pivot-product bytes in the tail (`02:43D8–4470`) [C]
The determinant sign comes from the permutation parity, not a separate sign cell. Each
physical row swap (`43B9`) calls `4259` to swap the matching pair in the permutation
vector at `84D5`; the determinant magnitude is the running product of the diagonal pivots
formed during back-elimination. The tail that closes the det/inverse pass:
```z80
43D8 (det branch, bit6 = det):
  43D9: BIT 6,A           ; det mode?
  43DE: CALL 151B         ; pop pivot
  43E3..43F6: PUSH AF ; (RST 8 _CpyToOP2) ; CALL 403c (load [M](i,j)) ;
              CALL 238b (_FPMult) ; DEC pivot/row counters (84B0)  ; loop
              → multiply the running determinant by each pivot
  43F8: POP AF ; AND 1 ; JP NZ,24bd    ;  *** DET SIGN ***  low bit of the
              ; permutation-swap count → conditional _InvOP1S (negate)
43FF (inverse branch): re-walk for the augmented-identity columns,
  4410..446F: per-column back-substitution (4428/445B = _FPMult-accumulate,
              442B/24bd = _InvOP1S sign flips), then JP 0x420F to undo the
              column permutation (4259-pairs) so the inverse comes out in the
              original row/col order.
```
So the sign byte is the LSB of the swap-count applied via `_InvOP1S` (`00:24BD`) at
`43FB`/`442B`; the pivot product is the `238B`/`RST 30h` accumulate over the diagonal in
`43E3–43F6`. The permutation undo (`420F`/`4259`) restores element order for the inverse. [C]

### `rref(` / `ref(` — separate driver, *not* `42A6` [C/H]
`rref(`/`ref(` do not re-enter the `42A6` Gauss-Jordan engine. A function-xref shows
`matrix_gauss_engine` (`02:42A6`) has exactly two callers — `mat_inverse_entry` (`02:5F80`,
flag 0) and `det_entry` (`02:5FC0`, flag 0x40); there is no third call site (byte-confirmed
above: `CD A6 42` appears exactly twice). So `det(`/`[A]⁻¹` are the only consumers of that
square-only, partial-pivoting driver. [C]

`rref(` (`BBh,A6h`) and `ref(` (`BBh,A5h`) are 2-byte `0xBB`-lead function tokens. On the
page-38 statement/expression evaluator (`eval_expr_inner` `38:59A4`), token `0xBB` is detected
and `parse_advance` consumes the prefix; the second byte is then dispatched through the
evaluator's class-3 (function-token) handler-pointer table at `38:7175` (`701A/7021/7026`
select the `0x4000`/`0x478C`/`0x7175` tables by class; `703A: CALL 0x0033` = `_LdHLind` jumps
the resolved handler). Their reduced-row-echelon elimination is therefore a distinct,
non-square-tolerant driver reached through that table — a separate routine from `42A6`, using
the same per-element FP primitives (`_FPDiv`/`_FPMult`/`_FPSub`) but with its own pivot loop
that tolerates rectangular matrices and rank deficiency (zero rows left in place, no
`SINGULAR MAT`). *The concrete rref/ref body sits behind the `38:7175` 2-byte handler table and
was not byte-isolated in this pass (the table is unanalyzed data in the DB); the architectural
fact that it is a separate driver, not `42A6`, is confirmed by the two-caller xref. [C for the
"separate driver" conclusion; H for the exact body address.]*

---

## 6. How it ties to the FP engine and the VAT [C]

- Every element is a `TIFloat` ([doc 06](06-floating-point.md)). Indexing produces a *pointer*; the value is then
  moved into `OP1`/`OP2` (`RST4` = load-9, `_Mov9B`, `_MovFrOP1`) and all arithmetic is the FP
  engine's `RST 30h`(`_FPAdd`)/`_FPMult`/`_FPDiv`/`_FPSub`/`_FPRecip`. There is no SIMD; a
  matrix multiply is literally thousands of these calls. Complex elements (lists/`[i]`) carry a
  `0x0C` flag and use 18-byte (two-float) elements, split via `_CplxOPArrange`.
- **Where the data lives:** the parser resolves the list/matrix name through `OP1` →
  `_FindSym`/`_ChkFindSym` ([doc 05](05-variables-vat.md)/sub-vat) → VAT entry → data pointer (+ flash page if
  archived). The `count`/`dim` header is read first; then `_AdrLEle`/`_AdrMEle` do pointer
  math. A store into an archived matrix/list unarchives to RAM first (`_Arc_Unarc`;
  Flash cannot be written in place).
- **Scratch RAM used by the algorithms** (verified operands): `84AF` (current dims / i,j loop
  state), `84B0/84B3/84B4` (pivot, k, row counters), `84B7` (dims copy), `84D3/84D5/84D7`
  (data pointers + the permutation vector base), `8478`=OP1, `8483`=OP2, `8499`=OP4,
  `84AF`=OP6 region = the matrix-op loop frame.

---

## 7. Errors raised on these paths [C]

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
| `0x15` | `E_Stat` (via `ram:2741`) | `_GetPosListElem` bad index (`_CkOP1Pos`) |

---

## 8. Confident address index

| space:addr | name | what |
|---|---|---|
| `00:10C4` | `_CreateRList` | new real list (`count*9+2`) [C] |
| `00:1109` | `_CreateCList` | new complex list (`count*18+2`) [C] |
| `00:1115` | `_CreateRMat` | new matrix (`H*L*9+2`, header `dim0,dim1`) [C] |
| `00:1EF6` | `_HTimesL` | element count = H*L (dims multiplied) [C] |
| `00:1930` | `_HLTimes9` | ×9 (real `TIFloat` stride) [C] |
| `02:4000` | `_AdrMRow` | address of matrix column start (column stride) [C] |
| `02:4002` | `_AdrMEle` | matrix element address: `((column-1)*dim0+(row-1))*9` [C] |
| `02:4044` | `_GetMToOP1` | `[M](i,j)` → OP1 [C] |
| `02:406C` | `_PutToMat` | OP1 → `[M](i,j)` (validated) [C] |
| `02:40BA` | matrix-multiply body | O(n³) triple loop, decoded from `rom.bin` (not a defined function in the live Ghidra DB); called from `02:5FFF`/`4605`/`5B39` (§4). `0x40BA` in ti83plus.inc is the unrelated `_SinCosRad` bcall ID. [C] |
| `02:4108` | `identity_build` | `identity(n)`: diagonal-1 fill (token 0xB4) [C] |
| `02:412A` | `mat_transpose` | transpose `[A]ᵀ` body (token `0x0E`, dispatched `60E9`/called `60FE`): per-cell copy `dst(c,r)=src(r,c)` via the swapped dest header (§4) [C] |
| `02:414E` | `mrow_swap_loop` | row swap/scale (elimination) [C] |
| `02:4178` | `mat_fill_type1` | live DB name; single-counter per-cell fill/apply loop in the `414A`–`4178` block — *not* transpose (§4) [C] |
| `02:4539` | `mele_copy9_d3` | bulk column-major float-payload copy (skip 2 dim bytes, `LDIR`); used by `augment(`/reshape (§4) [C] |
| `02:4663` | `mat_gauss_engine` | live DB name; `min(H,L)` partial-pivoting elimination engine; only caller is the `augment(` `0x91` branch (`6379`). Its role inside plain `augment(` is the one open item (§4) [H] |
| `02:4773` | `mat_to_list_cols` | `Matr►list(` 2-arg column-extract engine (only caller `63A0`): nested col×row walk copying matrix columns into list element(s) (§4) [C] |
| `02:5264` | `cplx_swap_dispatch` | live DB name; complex OP-pair arrange/swap (`5344`/`52D3`) reached only from the `0xBD` branch (`62D0`) — *not* the `0xB5`/`dim(` matrix-create branch (§4) [C] |
| `02:6238` | `mat_augment_copy` | `augment(` column-concat: allocate result (`5DE0`) + `4539` payload copy + re-point `84D3` (§4) [C] |
| `02:49E3` | `lele_copy_until_eq` | live DB name; list-element copy-until-length-match (`21BB`, `RET Z`); inner copy of the `Matr►list(` 1-arg/list path (`6397`) (§4) [C] |
| `02:41C1` | `abs_cmp_op1op2` | absolute-value compare: OP1 vs pivot [C] |
| `02:41D0` | `pivot_col_scan` | partial-pivot: find largest absolute value in column [C] |
| `02:4259` | `perm_swap` | swap two entries of the permutation vector (84D5) [C] |
| `02:426D`/`426F` | `col_dot_accum`/`col_dot_accum_from` | column dot-product / back-substitution accumulate [C] |
| `02:42A6` | `matrix_gauss_engine` | inverse(flag 0)/det(flag 0x40) Gauss-Jordan + partial pivot; square-only (`H==L` guard) [C] |
| `02:4473` | `ele_sub_ref` | `[M] − factor*pivot` element step (`_FPSub`) [C] |
| `02:461C` | `mat_max_abs` | maximum absolute element (pivot tolerance) [C] |
| `02:47C5` | `_AdrLEle` | list element address: `data+2+(i-1)*9` [C] |
| `02:47EA` | `_GetLToOP1` | list[i] → OP1 (complex-aware) [C] |
| `02:47FB` | `_RclListElemToOP1` | recall list elem to OP1 [C] |
| `02:47FE` | `_RclListElemB` | recall list elem (B-indexed) [C] |
| `02:4829` | `_PutToL` | OP1 → list[i] (validated, complex-aware) [C] |
| `02:49A7` | `_RclCListElem` | complex-list element → OP1/OP2 [C] |
| `02:49B5` | `_RclCListElemB` | complex-list element (B-indexed) [C] |
| `02:5BBB` | `_GetPosListElem` | list element by positive index (bounds) [C] |
| `02:5E46` | `func_eval_dispatch` | single-byte function-token evaluator (0xB0–0xCD) [C] |
| `02:5F80` | `mat_inverse_entry` | `[A]⁻¹`: flag 0 → `matrix_gauss_engine` [C] |
| `02:5FC0` | `det_entry` | `det(`: flag 0x40 → `matrix_gauss_engine` [C] |
| `02:6104` | `list_fold_dispatch` | `sum(`/`prod(` higher-order list fold [C] |
| `02:69B7` | `chk_op_is_matrix` | require operand type==2 else E_DataType [C] |
| `ram:21C4` | `chk_type_lt_1a` | classify element type width: `AND 0x1F ; CP 0x1A ; CP 0x18 ; CCF` — real-vs-complex (0x0C) element width [C] |
| `35:79E9` | `_ListIdxTimes9` | list index ×9 + dispatch [C] |
| `07:4D3B` | `_RedimMat` | re-dimension matrix/list [C] |
| `07:4F07` | `_InsertList`/`_IncLstSize` | grow a list in place [C] |
| `07:4F43` | `_DelListEl` | delete list element(s) [C] |
| `38:6C8F` | `_StMatEl` | parser store into `[M](r,c)` (bounds-checked) [C] |
| `38:741F`/`7422` | `_ConvDim`/`_ConvDim00` | coerce a dim/index to real [C] |
| `00:26F0` | `_ErrSingularMat` | `E_SingularMat 0x83` [C] |
| `00:26F8` | `_ErrIncrement` | `E_Increment 0x85` [C] |
| `00:2715` | `_ErrDimMismatch` | `E_DimMismatch 0x8B` [C] |
| `00:2719` | `_ErrDimension` | `E_Dimension 0x8C` [C] |

---

## 9. Open items
- **RESOLVED** — `rref(`/`ref(` use a separate driver, not `42A6`. Xref proves `42A6` has
  exactly two callers (inverse `5F80`, det `5FC0`); rref/ref are 2-byte `0xBB`-lead function
  tokens dispatched via the page-38 evaluator's class-3 handler table at `38:7175` (§5). The
  *exact rref/ref body* sits behind that (unanalyzed-data) table and is the only residual: its
  start address was not byte-isolated, but it is confirmed *not* `42A6`.
- **RESOLVED** — det sign / pivot-product (`42A6` tail `43D8–4470`) and dim labelling. The det
  sign = LSB of the permutation-swap count applied via `_InvOP1S` (`24BD`) at `43FB`/`442B`;
  the magnitude is the `238B`/`RST 30h` diagonal-pivot accumulate (`43E3–43F6`); `420F`/`4259`
  undo the column permutation for the inverse (§5). Row/col vs dim0/dim1 is now [C]:
  `dim0` (first header byte) = #rows, and `_AdrMEle` takes `B=column`, `C=row` (§1/§2).
- **RESOLVED** — transpose, `Matr►list(`, and the `augment(` column-concat bodies. Each command's
  page-02 dispatch site and body are byte-confirmed, every body having exactly one caller (§4):
  - transpose `[A]ᵀ` (token `0x0E` @ `60E9`) → `02:412A` (only caller `60FE`): the dim header is
    swapped (`60F5`) and `412A` copies `dst(c,r)=src(r,c)` over every cell. `02:4178` is a separate
    single-counter fill/apply, not transpose. [C]
  - `Matr►list(` (`0x8D` @ `6388`) → `02:4773` (2-arg column-extract engine, only caller `63A0`)
    with `02:49E3` as the 1-arg/list inner copy. [C]
  - `augment(` (`0x91` @ `635B`) → equal-rows guard (`CP L ; JP NC,2719`) + column-concat copy at
    `02:6238` (`5DE0` allocate + `02:4539` `LDIR` payload copy). [C]
  - `dim(` (`0xB5` @ `62D4`; `0xB5` = `tDim`, *not* `randM(`) → creates the result and sets its
    dims (`5DBB`/`5DEB`). `02:5264` (`cplx_swap_dispatch`, only caller `62D0` in the `0xBD` branch)
    is reached only from that complex branch, not here. [C]
  - `List►matr(` `0x8E` branch (`61C1`) → `02:7D19` + `_DataSize` copy (`4539`/`453F`) is
    unchanged [H].
- **OPEN — two residuals inside the confirmed branches** (§4):
  - `augment(`'s `0x91` branch calls `02:4663` (`mat_gauss_engine`, only caller `6379`) — a
    `min(H,L)` partial-pivoting elimination pass — after the column-concat copy. Its role for plain
    `augment(` is byte-confirmed as a call but not explained. [H]
  - `randM(`'s per-cell random fill body is unidentified. `randM(` is a 2-byte token
    (`tRandM` = `0x20`, `0xBB`-prefix group), distinct from the `0xB5`/`dim(` branch; the visible
    matrix-create/dim-convert code is `dim(`'s, not randM's. randM does not go through the
    `_Random` bcall (`0x4B79`) — a ROM-wide scan finds no `RST 28h; .dw 0x4B79` site. [H]
- `seq(`/`SortA(`/`SortD(`/stats list-builders: confirm the collect-then-`_CreateRList` loop
  and the in-place float sort/compare. (Residual — comparator `_CpOP1OP2` confirmed; the
  unanalyzed page-02 sort body's element-load is still not byte-traced.)
