# Matrices & Lists

*TI-84 Plus OS 2.55MP — feature deep dive.*

How the TI-84 Plus OS (2.55MP) actually stores, indexes, and computes on **lists** and
**matrices** — the routines a college student hits doing linear algebra (`det(`, `[A]⁻¹`,
`rref(`, `[A]*[B]`, `identity(`, `T`) and data work (`L1+L2`, `dim(`, `sum(`, `seq(`,
`SortA(`). Companion to [05-variables-vat.md](05-variables-vat.md) (where the data lives), [06-floating-point.md](06-floating-point.md)
(how each element is computed), and [sub-vat-archive.md](sub-vat-archive.md) (Store/Recall/Archive).

All `page:addr` verified by **disassembling the Z80** in the private Ghidra copy
(`/tmp/ti84-matlist`, headless `Dec.java`/`Disasm.java`), not just the decompiler.
Page numbers are the masked flash page (`rawpage & 0x3F`). The whole-OS image lives in one
Ghidra program with address spaces `ram` (the page-0/RAM-resident 0x0000–0x7FFF window) and
`page_NN` for each flash page mapped into the 0x4000–0x7FFF bank-A window.

Confidence (this doc's shorthand; see [Conventions](conventions.md)): **[C]=confirmed from disassembly** (≈`[confirmed]`), **[H]=high (structure clear, light inference)** (≈`[standard]`), **[I]=inferred / standard documented TI behaviour** (≈`[hypothesis]`).

---

## 0. TL;DR — the mental model

- A **list** is `word count` (2 bytes) followed by `count` × 9-byte `TIFloat` elements
  (18-byte complex elements if the list is complex, flagged `0x0C`). Element $i$ (1-based)
  lives at $\mathrm{addr}(L_i)=\mathrm{data}+2+(i-1)\cdot 9$.
- A **matrix** is `byte dim0; byte dim1;` (two 1-byte dimensions) followed by
  `dim0*dim1` × 9-byte `TIFloat`, stored **column-major**. The element offset from the start
  of the data area (after the 2 dim bytes) is

  $$\mathrm{offset}=\big((\mathit{idx}_0-1)\cdot \mathit{dim}_0+(\mathit{idx}_1-1)\big)\times 9$$
- **Every element read/write routes one `TIFloat` through `OP1`/`OP2`** and the FP engine —
  there is no "vector unit"; matrix multiply is just a triple loop of `_FPMult`+`_FPAdd`.
- The data area is found through the **VAT** (`_FindSym`, [doc 05](05-variables-vat.md)): the VAT entry's data
  pointer + page byte locate the `count`/`dim` header, after which all indexing is pointer
  arithmetic computed by `_AdrLEle`/`_AdrMEle`.
- **One shared Gauss-Jordan engine** (`page_02:42A6`) implements **matrix inverse `[A]⁻¹`**
  (flag `0x00`) and **`det(`** (flag `0x40`) with **partial pivoting**. `rref(`/`ref(` are
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
- **`_HTimesL` (`00:1EF6`)** is literally `result = H * L` (`B=H; HL=Σ L`, a `DJNZ` add loop) —
  it computes the **element count** from the two dimension bytes. [C]
- Header = two bytes `dim0,dim1`; data is `dim0*dim1` floats **column-major**.

> **Dimension naming [C].** Settled by disassembly. `_AdrMEle` (`02:4002`) reads the header's
> **first byte** (`LD A,(DE); LD L,A`) and uses it as the **major stride**, looping `(B−1)`
> adds of it and then `+(C−1)` *within* a column (column-major). The major stride of a
> column-major array is the **number of rows**, so the **first header byte (`dim0`) = #rows**,
> and `_AdrMEle`'s `B = idx0 = column`, `C = idx1 = row`. `_CreateRMat` (`ram:1115`) confirms
> the layout: it is `PUSH HL ; CALL _HTimesL (1EF6) ; LD A,2 ; JR 10DD` — `_HTimesL` returns
> `H·L` (the element count) and `A=2` is the 2-byte dim header; the two dimension bytes are
> stored `dim0` (rows) then `dim1` (cols). The byte-confirmed index arithmetic
> `((idx0−1)·dim0 + (idx1−1))·9` is therefore a **(column, row)** register convention with a row-count stride.

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
So **list element *i* is at `data + 2 + (i−1)*9`** (×18 path for complex). `_HLTimes9`
(`00:1930`) is the universal "multiply by 9" (real `TIFloat` size). `FUN_ram_21c4` (`ram:21C4`)
masks the type to ≤0x19 and sets carry for the complex case (drives the 18-byte width). [C]

Convenience wrappers (all = `_AdrLEle` then a 9-byte move through OP1, complex-aware): [C]
- **`_GetLToOP1` (`02:47EA`)** — list[i] → OP1 (real or complex via two `_Mov9B`).
- **`_RclListElemToOP1` (`02:47FB`)**, **`_RclListElemB` (`02:47FE`)** — recall to OP1 with the
  index pre-loaded in RAM (`84AF`/`84D3`).
- **`_PutToL` (`02:4829`)** — OP1 → list[i]; `_CkValidNum` validates the float first, then
  copies, honoring the complex (`& 0xC`) element width.
- **`_RclCListElem` (`02:49A7`)**, **`_RclCListElemB` (`02:49B5`)** — complex-list element via
  `_CplxOPArrange` (splits real/imag into OP1/OP2).
- **`_GetPosListElem` (`02:5BBB`)** — fetch by a *positive-integer* index with `_CkOP1Pos`
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
**Column-major offset: `elem = data + 2 + ((idx0−1)*dim0 + (idx1−1)) * 9`.** The `(B-1)`
adds of `dim0` walk whole columns; the `(C-1)` steps within a column. The 8-bit adds track
a carry into `H` so the address is a true 16-bit offset (matrices up to 99×99). Because the
multiplied byte is `dim0` and that is the **row count** (column-major major stride), **`B=idx0`
is the column index and `C=idx1` is the row index** — see the [C] dimension-naming note in §1. [C]

Matrix element wrappers: [C]
- **`_AdrMRow` (`02:4000`)** — address of the *start of column idx0* in the column-major buffer
  (loops `(idx0−1)` × dim0, no `+(idx1-1)`); whole-row operations layer their own iteration on top.
- **`_GetMToOP1` (`02:4044`)** — `[M](r,c)` → OP1 (`_AdrMEle` then `RST4` = load 9 bytes).
- **`_PutToMat` (`02:406C`)** = `FUN_02_4068`: `_AdrMEle ; _CkValidNum ; _MovFrOP1` — OP1 →
  `[M](r,c)` with validation.
- **`_StMatEl` (`38:6C8F`)** — high-level "store into `[M](r,c)`" used by the parser: resolves
  the matrix name (`5F45`), bounds-checks indices against the dims (`r≤rows && c≤cols`, else
  `_JError 0x8C` = `E_Dimension`), unarchives if needed, then `_PutToMat`. [C/H]

### Internal index helpers reused by the algorithms [C]
- **`FUN_02_403C`** = `_AdrMEle(currentIJ) ; RST4` — "load `[M](i,j)` to OP1" (the elimination
  inner-loop read). Indices come from the loop state at `84AF/84B3/84B4`.
- **`FUN_02_4051`** = `_AdrMEle ; _Mov9B(→OP3@8483)` — load element to OP3.
- **`FUN_02_405A`/`405E`** = `_AdrMEle ; _CkValidNum ; _MovFrOP1` — store OP1 back to `[M](i,j)`.
- **`_ListIdxTimes9` (`35:79E9`)** = `_HLTimes9(idx)` then a small dispatch (`RST4`) — the list
  analogue used in a few list-builder paths.

---

## 3. List operations [C/H]

### Create / resize / insert / delete
| Routine | addr | Role |
|---|---|---|
| `_CreateRList` | `00:10C4` | new real list: `count*9+2` bytes (§1) [C] |
| `_CreateCList` | `00:1109` | new complex list: `count*18+2` [C] |
| `_InsertList` / `_IncLstSize` | `07:4F07` (body `07:4EF4`) | grow a list in place via `_InsertMem`; caps length, else `E_Increment 0x8C`-class [C] |
| `_DelListEl` | `07:4F43` | delete element(s): `_HLTimes9(index)` to size the gap (×2 if complex, `& 0x1F == 0x0D`), then `_DelMem` via a cross-page jump [C] |
| `_RedimMat`/`_ConvDim` | `07:4D3B` / `38:741F` | re-dimension (shared with matrices); `_ConvDim`/`_ConvDim00` (`38:741F/7422`) coerce OP1 to a real index first [C] |

### `dim(`, `dim(L)→n`, list↔value
`dim(` reads the `count` word straight from the list header; assigning `n→dim(L)` calls the
resize path (`_IncLstSize`/`_DelListEl`) to grow/shrink, zero-filling new cells. List→matrix
and matrix→list (`List►matr(`, `Matr►list(`) reshape via `_DataSize` + a column-major copy
(`FUN_02_4539`/`453F`, a `_DataSize`-counted byte copy of the float payload). [H]

### List arithmetic `L1+L2`, scalar broadcast
Binary list ops are **element-wise folds**: the parser walks both lists by index, loads
`L1[i]`→OP1, `L2[i]`→OP2, applies the FP RST shortcut (`RST 30h _FPAdd`, `_FPSub`, `_FPMult`,
`_FPDiv`), stores into a freshly `_CreateRList`'d result. Length mismatch ⇒ `E_DimMismatch`
(`_ErrDimMismatch 00:2715`, `0x8B`); a list⊕scalar broadcasts the scalar across every element.
[H — the per-element FP path is confirmed; the outer driver is the parser's binary-op handler.]

### `sum(`, `prod(` — higher-order folds over a list [C]
Tokens **`0xB6`=`sum(`**, **`0xB7`=`prod(`** load a *combiner function pointer* and fold the
list (dispatcher `02:6104`):
```
sum(  : HL = 0x3A83 (cross-page → FP add-accumulate),  seed via _OP1Set0
prod( : HL = 0x49B9 (seed accumulator = 1.0, _PushOP1), combine with _FPMult
        CALL 0x64B7 ; ... ; JP (HL)   ; apply the combiner across e1..eN
```
The fold seeds the accumulator (0 for sum, 1 for prod), then for each element does
`acc = combine(acc, L[i])` through OP1/OP2. Works on real **and** complex lists (`type 1`/`0xD`
both route to `02:6140`). [C]

### `seq(`, `cumSum(`, `SortA(`/`SortD(`, `mean(`/`median(`/`stdDev(` [H/I]
- **`seq(expr,var,lo,hi[,step])`** evaluates `expr` for `var = lo..hi`, pushing each result
  and finally `_CreateRList`-ing the collected floats (the generic list-builder loop;
  `_SetSeqM 36:7D1F` is the sequence-graph variant). [H]
- **`cumSum(`** is a running `_FPAdd` writing back each partial sum (the sum-fold with the
  accumulator stored every step). [I]
- **`SortA(`/`SortD(`** — list sort in place (`SortA(` co-sorts dependent lists); the comparator
  and per-element sort key are detailed in the next subsection. [confirmed comparator]
- Stats (`mean/median/sum/stdDev/variance`) are list folds layered on `sum(`/sort. [I]

### `SortA(` / `SortD(` — list sort [confirmed comparator]

`SortA(` (`tSortA` `0xE3`) and `SortD(` (`tSortD` `0xE4`) sort a list **in place** — ascending and
descending respectively; `SortA(L1,L2,…)` co-sorts the trailing lists by the same permutation. This
is the **command** sort, distinct from the stat-internal `stat_sort` (`3A:7935`) that backs median/
quartile/Med-Med (see [Statistics](sub-statistics.md)).

The sort body is on **page 0x02** (around `02:5939`); it is reached only through the parser's
computed command dispatch, so Ghidra leaves it as unnamed code. Its comparator is **`_CpOP1OP2`**
(`00:198D`), confirmed by the call at `02:5939`.

**`_CpOP1OP2` compares two `TIFloat`s as real numbers** [confirmed from disassembly]: it tests the
**sign** (type byte bit 7), then the **exponent**, then the **mantissa** digits, and returns the
ordering. It does not compute a magnitude and does not read an imaginary part. Each comparison
therefore orders elements by the single 9-byte `TIFloat` the sort holds in `OP1`/`OP2`:

| List element | Sort key |
|--------------|----------|
| real | the value (sign → magnitude) |
| complex | the **real part** only; the imaginary part is not read, and elements with equal real parts keep their input order |

No element type is ordered by magnitude/modulus (`_CAbs` is never on this path). [comparator and
its real-number semantics confirmed; the per-element sort key follows from them — the unanalyzed
sort body's element-load is not byte-traced]

---

## 4. Matrix operations [C]

### `dim(`, redim, identity, copy
- **`dim([M])`** reads the two header bytes → a 2-element list `{rows,cols}`; **`{r,c}→dim([M])`**
  reallocates via `_RedimMat` (`07:4D3B`), preserving overlapping cells and zero-filling new
  ones. [C/H]
- **`identity(n)` (token `0xB4` → `FUN_02_4108`)** [C]: allocate `n×n`, then walk every cell
  writing `1.0` when `row==col` (the `exp==type` test) and `0` otherwise:
  ```
  _OP1Set1 ; for each (i,j): if i==j -> store 1.0 (mantissa[0]=0x10) else 0
  ```
- **`Fill(value,[M])`** / **`randM(`** stamp a constant / random values across all cells
  (element loop `FUN_02_412A` applies a per-element op over the whole matrix). [H]
- Matrix **copy/reshape** = `_DataSize`-counted byte copy of the float payload
  (`FUN_02_4539`/`453F`). [C]

### `[A] + [B]`, `[A] - [B]`, scalar·[A] — element-wise [C]
`FUN_02_412A` is the **per-element matrix apply**: nested `for col { for row { load [M](r,c)→OP1;
op; store } }` driving the FP RSTs. Binary matrix add/sub require equal dims
(`_ErrDimMismatch 0x8B`).

### `[A] * [B]` — matrix multiply [C]
**`FUN_02_40BA`** (reached from the `*` token at `02:5FE6` when both operands are matrices,
after `FUN_02_5766` sets up the result dims and `FUN_02_4539` preps storage). Classic O(n³)
triple loop with an FP accumulator:
```
for each result cell (i,j):
    _OP1Set0                              ; acc = 0
    for k = 1 .. inner:
        load [A](i,k) -> OP1   (403C)
        multiply by [B](k,j)   (4049/47B9 = FP multiply-accumulate)
        acc += product         (_CpyTo2FPST / 479F)
    store acc -> [C](i,j)      (405A)
```
Loop counters live at `84B0` (outer), `84B3` (k, inner), `84B4`/dims at `84AF`. Inner-dim
mismatch (`A.cols ≠ B.rows`) ⇒ `_ErrDimMismatch`. Each multiply/add is a full `TIFloat` FP op,
so an `n×n` product is `n³` `_FPMult` + `_FPAdd` calls. [C]

### Transpose `[A]ᵀ` — driver `02:4178` [C]
The transpose token (`tTranspose`) routes through the page-02 function evaluator
(`func_eval_dispatch` family) to **`mat_transpose` @ `02:4178`**: it allocates the result, sets
the swapped dim into the loop frame (`84B5` from `84B7`), then walks `(i,j)` reading
`[A](i,j)`→OP1 via `402C`/`47B9` and storing through `_PutToMat` (`4068`), i.e.
`dst(c,r) = src(r,c)` — a re-indexed column-major copy reusing `_AdrMEle`. It shares the
element-loop framing with `mat_elementwise` (`412A`) and the row ops (`414E`). [C]

### `augment(`, `randM(`, `List►matr(`, `Matr►list(` — per-function drivers [C]
These are dispatched from the page-02 function-token evaluator (the `CP imm ; JR/JP` chain at
`02:55xx`–`63xx` keyed on the token byte), each with its **own driver** on page 02: [C]

| Token | site (page 02) | driver | what it does |
|---|---|---|---|
| `augment(` | `0x91` @ `635B` | **`02:4663`** | type-checks both operands are matrices, `LD A,H ; CP L` rejects a row-count mismatch (`E_Dimension 2719`), then concatenates columns: a partial-pivot-style scan-free copy of `[A]`'s then `[B]`'s columns into a `rows × (colsA+colsB)` result. (`augment(L1,L2)` list-concat is the `0x92` sibling at `637F`.) |
| `randM(` | `0xB5` @ `62D4` | `02:5264`/`5344` | allocates the `r×c` result and stamps a random `TIFloat` (via `_Random`) into every cell — the matrix `Fill(`-style element loop. |
| `Matr►list(` | `0x8D` @ `6388` | `02:49E3`/`4773` | column-major copy of matrix columns out into list(s); length-checks via `21BB`. |
| `List►matr(` | `0x8E` @ `61C1` | `02:7D19` + copy | reshapes the argument lists into a matrix (`_DataSize`-counted float copy `4539`/`453F`). |

The shared element-loop kernels these drivers call are the confirmed `mat_elementwise`
(`02:412A`), `mat_row_op` (`02:414E`) and `mat_transpose` (`02:4178`) family; the per-function
drivers above are now byte-pinned at their evaluator entries. [C]

---

## 5. THE heavy ones — `det(`, `[A]⁻¹`, `rref(` / `ref(` [C]

All three are the **same Gauss-Jordan elimination engine with partial pivoting**:
**`matrix_gauss_engine` @ `page_02:42A6`**. The *entry flag in `A`* selects behaviour. Only two
direct call sites exist (byte-verified — `CD A6 42` appears exactly twice):

| Token / op | site | flag `A` | meaning |
|---|---|---|---|
| `[A]⁻¹` (`^` token `0x0C`, operand = matrix) | `02:5F80` | `0x00` | **inverse**; singular ⇒ error |
| `det(` (token `0xB3`) | `02:5FC0` | `0x40` | **determinant**; bit6 set ⇒ singular tolerated (returns 0) |

`det(`'s handler (`02:5FA3`) first type-checks the operand is a matrix (`FUN_02_69B7`:
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
Key sub-routines (all `page_02`): [C]
- **`461C`** — compute the matrix's **max-abs element** (numeric scale for the near-zero pivot
  test).
- **`41C1`** — `|OP1|` vs `|pivot|` compare (`_AbsO1O2Cp`); **`41D0`** — scan a column for the
  **largest-magnitude pivot** (partial pivoting), calling `43B9` to swap rows as it goes.
- **`43B9` / `414E` / `_AdrMRow`** — physical **row swap / row scale** (whole-row moves).
- **`4259`** — swap two entries in the **permutation vector** at `84D5`.
- **`4473`** — the elimination element step (`[M](i,k) − factor*[M](pivot,k)` via `_FPSub`).
- **`426D` / `426F`** — row dot-product / back-substitution accumulate (`_FPMult` + `RST6`).
- Pivot normalize uses **`_FPRecip`** / **`_FPDiv`**; sign/inverse use `_InvOP1S`.

**`det(`** therefore = forward elimination with partial pivoting, **return the signed product
of the pivots** (each row swap flips the sign); a zero pivot ⇒ `det = 0` (no error).
**`[A]⁻¹`** = full Gauss-**Jordan** (reduce to identity, the augmented identity becomes the
inverse); a zero pivot ⇒ `ERR:SINGULAR MAT`.

#### Det sign / pivot-product bytes in the tail (`02:43D8–4470`) [C]
The determinant sign comes from the **permutation parity**, not a separate sign cell. Each
physical row swap (`43B9`) calls **`4259`** to swap the matching pair in the permutation
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
So the **sign byte is the LSB of the swap-count** applied via `_InvOP1S` (`02:24BD`) at
`43FB`/`442B`; the **pivot product** is the `238B`/`RST 30h` accumulate over the diagonal in
`43E3–43F6`. The permutation undo (`420F`/`4259`) restores element order for the inverse. [C]

### `rref(` / `ref(` — separate driver, **not** `42A6` [C/H]
**`rref(`/`ref(` do NOT re-enter the `42A6` Gauss-Jordan engine.** A function-xref shows
`matrix_gauss_engine` (`02:42A6`) has **exactly two callers** — `mat_inverse_entry` (`02:5F80`,
flag 0) and `det_entry` (`02:5FC0`, flag 0x40); there is no third call site (byte-confirmed
earlier: `CD A6 42` appears exactly twice). So `det(`/`[A]⁻¹` are the only consumers of that
square-only, partial-pivoting driver. [C]

`rref(` (`BBh,A6h`) and `ref(` (`BBh,A5h`) are **2-byte `0xBB`-lead function tokens**. On the
page-38 statement/expression evaluator (`eval_expr_inner` `38:59A4`), token `0xBB` is detected
and `parse_advance` consumes the prefix; the second byte is then dispatched through the
evaluator's **class-3 (function-token) handler-pointer table at `38:7175`** (`701A/7021/7026`
select the `0x4000`/`0x478C`/`0x7175` tables by class; `703A: CALL 0x0033` = `_LdHLind` jumps
the resolved handler). Their reduced-row-echelon elimination is therefore a **distinct,
non-square-tolerant driver** reached through that table — a separate routine from `42A6`, using
the same per-element FP primitives (`_FPDiv`/`_FPMult`/`_FPSub`) but with its own pivot loop
that tolerates rectangular matrices and rank deficiency (zero rows left in place, no
`SINGULAR MAT`). *The concrete rref/ref body sits behind the `38:7175` 2-byte handler table and
was not byte-isolated in this pass (the table is unanalyzed data in the DB); the **architectural
fact that it is a separate driver, not `42A6`, is confirmed** by the two-caller xref. [C for the
"separate driver" conclusion; H for the exact body address.]*

---

## 6. How it ties to the FP engine and the VAT [C]

- **Every element is a `TIFloat`** ([doc 06](06-floating-point.md)). Indexing produces a *pointer*; the value is then
  moved into `OP1`/`OP2` (`RST4` = load-9, `_Mov9B`, `_MovFrOP1`) and all arithmetic is the FP
  engine's `RST 30h`(`_FPAdd`)/`_FPMult`/`_FPDiv`/`_FPSub`/`_FPRecip`. There is no SIMD; a
  matrix multiply is literally thousands of these calls. Complex elements (lists/`[i]`) carry a
  `0x0C` flag and use 18-byte (two-float) elements, split via `_CplxOPArrange`.
- **Where the data lives:** the parser resolves the list/matrix name through `OP1` →
  `_FindSym`/`_ChkFindSym` ([doc 05](05-variables-vat.md)/sub-vat) → VAT entry → data pointer (+ flash page if
  archived). The `count`/`dim` header is read first; then `_AdrLEle`/`_AdrMEle` do pointer
  math. A store into an **archived** matrix/list unarchives to RAM first (`_Arc_Unarc`, you
  can't poke Flash in place).
- **Scratch RAM used by the algorithms** (verified operands): `84AF` (current dims / i,j loop
  state), `84B0/84B3/84B4` (pivot, k, row counters), `84B7` (dims copy), `84D3/84D5/84D7`
  (data pointers + the permutation vector base), `8478`=OP1, `8483`=OP3, `8499`=OP6/type,
  `84AF`-region = the matrix-op loop frame.

---

## 7. Errors raised on these paths [C]

| `_JError` code | name | raised by |
|---|---|---|
| `0x78` | 0-index reject (via `ram:2793`) | `_AdrMEle`/`_AdrMRow` on a 0 row/col index |
| `0x83` | `E_SingularMat` (`ERR:SINGULAR MAT`) | `42A6` inverse on a zero pivot (`_ErrSingularMat 00:26F0`) |
| `0x85` | `E_Increment` | `_ErrIncrement 00:26F8` (bad seq/loop step) |
| `0x89` | `E_DataType` | `det(`/matrix ops on a non-matrix operand (`FUN_02_69B7`) |
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
| `02:40BA` | retired label | not a live function in the current Ghidra DB; matrix multiply body remains unresolved here |
| `02:4108` | `identity_build` | `identity(n)`: diagonal-1 fill (token 0xB4) [C] |
| `02:412A` | `mat_elementwise` | per-element matrix unary/binary apply [C] |
| `02:414E` | `mat_row_op` | row swap/scale (elimination) [C] |
| `02:4178` | `mat_transpose` | `[A]ᵀ`: `dst(c,r)=src(r,c)` re-indexed copy [C] |
| `02:4663` | `mat_augment` | `augment(` column-concat (rows must match) [C] |
| `02:5264` | `mat_randm` | `randM(` random-fill driver [C] |
| `02:49E3` | `matr_to_list` | `Matr►list(` column→list copy [C] |
| `02:41C1` | `pivot_abs_cmp` | absolute-value compare: OP1 vs pivot [C] |
| `02:41D0` | `pivot_col_scan` | partial-pivot: find largest absolute value in column [C] |
| `02:4259` | `perm_swap` | swap two entries of the permutation vector (84D5) [C] |
| `02:426D`/`426F` | `row_dot_accum` | dot-product / back-substitution accumulate [C] |
| `02:42A6` | `matrix_gauss_engine` | **inverse(flag 0)/det(flag 0x40)** Gauss-Jordan + partial pivot [C] |
| `02:4473` | `elim_sub_step` | `[M] − factor*pivot` element step (`_FPSub`) [C] |
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
| `ram:21C4` | `classify_elem_width` | real-vs-complex (0x0C) element width [C] |
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
- **RESOLVED — `rref(`/`ref(` use a separate driver, not `42A6`.** Xref proves `42A6` has
  exactly two callers (inverse `5F80`, det `5FC0`); rref/ref are 2-byte `0xBB`-lead function
  tokens dispatched via the page-38 evaluator's class-3 handler table at `38:7175` (§5). The
  *exact rref/ref body* sits behind that (unanalyzed-data) table and is the only residual: its
  start address was not byte-isolated, but it is confirmed **not** `42A6`.
- **RESOLVED — det sign / pivot-product (`42A6` tail `43D8–4470`) and dim labelling.** The det
  sign = LSB of the permutation-swap count applied via `_InvOP1S` (`24BD`) at `43FB`/`442B`;
  the magnitude is the `238B`/`RST 30h` diagonal-pivot accumulate (`43E3–43F6`); `420F`/`4259`
  undo the column permutation for the inverse (§5). Row/col vs dim0/dim1 is now **[C]**:
  `dim0` (first header byte) = #rows, and `_AdrMEle` takes `B=column`, `C=row` (§1/§2).
- **RESOLVED — per-function matrix drivers.** `augment(`→`02:4663`, `randM(`→`02:5264`,
  `Matr►list(`→`02:49E3`, `List►matr(`→`02:7D19`, transpose `[A]ᵀ`→`02:4178` (§4).
- `seq(`/`SortA(`/`SortD(`/stats list-builders: confirm the collect-then-`_CreateRList` loop
  and the in-place float sort/compare. (Residual — comparator `_CpOP1OP2` confirmed; the
  unanalyzed page-02 sort body's element-load is still not byte-traced.)
