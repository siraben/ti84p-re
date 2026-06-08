# 05 — Variables & the VAT (Variable Allocation Table)

> **Deep dive:** [Variables, Archive & Unarchive](sub-vat-archive.md) — Store/Recall, the byte-verified `_FindSym` walk, and archive/unarchive.

Every named object the user creates — reals, lists, matrices, strings, programs, pictures, appvars, groups — is catalogued in the `VAT`, a table in RAM that grows *downward* from a fixed top. The VAT stores metadata + where the data lives; the data itself sits elsewhere in RAM (or in archived flash).

## Object types — `TIVarType` enum [confirmed — generated `tools/ty_vartype.txt`, per `ti83plus.inc`]

| Val | Name | Val | Name |
|-----|------|-----|------|
| 0x00 | RealObj | 0x0C | CplxObj |
| 0x01 | ListObj | 0x0D | CListObj |
| 0x02 | MatObj | 0x0E | UndefObj |
| 0x03 | EquObj | 0x0F | WindowObj |
| 0x04 | StrngObj | 0x10 | ZStoObj |
| 0x05 | ProgObj | 0x11 | TblRngObj |
| 0x06 | ProtProgObj | 0x12 | LCDObj |
| 0x07 | PictObj | 0x13 | BackupObj |
| 0x08 | GDBObj | 0x14 | AppObj |
| 0x09 | UnknownObj | 0x15 | AppVarObj |
| 0x0A | UnknownEquObj | 0x16 | TempProgObj |
| 0x0B | NewEquObj | 0x17 | GroupObj |

The active object's type byte is held in `varType` (`0x85D0`); the current var being processed in `curType` (`0x8450`). Both are typed `TIVarType` in the DB.

## How a variable is named/found

The OS passes variable identity through `OP1` as a "name string": `OP1[0]` = type byte, `OP1[1..]` = the name (token/bytes). The lookup/create family all key off OP1:

| Routine | Addr | Role |
|---------|------|------|
| `_FindSym` | `00:0E65` | find the VAT entry named by OP1; returns ptr/page (also the `RST 10h` fast path: vector `00:0010` → `JP 0E65`) |
| `_ChkFindSym` | `00:0E60` | type-classify OP1 (via the helper at `ram:2042`, which calls `_CkOP1Real` `00:1942` then checks the findable var classes) then `_FindSym` |
| `_CreateReal` | `00:10B8` | make a RealObj named by OP1 |
| `_CreateReal`/`_CreateCplx`/`_CreateRList`/`_CreateCList`/`_CreateRMat`/`_CreateStrng`/`_CreateProg`/`_CreateAppVar`/… | `00:10B0–00:1153` | one exported creator bcall per *creatable* variable class — ~13 `_Create*` routines covering the creatable classes, not one per `TIVarType` (no `_CreateList`/`_CreateMat`/`_CreateStr`); some object types are made only by internal routines with no public `_Create*` bcall (e.g. the `GroupObj` creator at `00:1157`, called from `39:73AF`) |
| `_DelVar`/`_DelVarArc` | `00:1308`/`00:12D9` | delete (and handle archived copies) |
| `_InsertMem`/`_DelMem` | `00:0F81`/`00:1368` | public low-level grow/shrink of a RAM region (the create path instead uses the internal gap routine at `ram:0F0C`) |

`_CreateReal` (recovered): sets the type byte and a fixed size of 9, then jumps to the common create core at `00:1011`. That core stores the type, type-checks the object (`chk_type_not_str` at `ram:2045`), handles the complex-list special case (`OP1.exp == 0x5D`), applies the 6-character name limit (`00:1023 CP 0x7`; `00:1025 JP NC,00:2700 → LD A,0x88`, `E_Syntax`), and carves the gap via the internal routine at `ram:0F0C` (`00:1034`). Aggregate creators (lists/matrices) instead enter through the size prelude `var_alloc` (`00:1005`), which computes count×element-size + the 2-byte header and raises `E_Memory` on overflow (`JP C,00:2721` at `00:1008` → `LD A,0x8E`) before falling into the same `00:1011` core.

## Variable data formats — rendered as C [confirmed from the `_Create*` family / DB types]

A VAT entry points at the variable's data, whose layout depends on the object type. Every numeric value is a 9-byte BCD `TIFloat` (see [Floating-Point](06-floating-point.md)); aggregates are a small header followed by an element array or a tokenized blob. These mirror the project's DB types (`TIFloat`, `TIComplex`, `TIListHdr`, `TIMatrixHdr`), with fields shown in ROM byte order:

```c
/* ── numeric primitives ───────────────────────────────────────────── */
typedef struct {
    uint8_t type;          /* 0x00 real, 0x80 negative; 0x0C/0x8C = complex part  */
    uint8_t exp;           /* base-10 exponent, biased by 0x80 (0x80 == 10^0)     */
    uint8_t mantissa[7];   /* 14 packed BCD digits, normalized d.dddddddddddddd   */
} TIFloat;                                                       /* 9 bytes  */
typedef struct { TIFloat re, im; } TIComplex;                   /* 18 bytes */

/* ── aggregate data (what the VAT entry's dataAddr points at) ──────── */
struct List   { uint16_t count;       TIFloat elem[/* count */];         }; /* ListObj 1; CListObj 0x0D uses TIComplex[] */
struct Matrix { uint8_t  rows, cols;  TIFloat elem[/* rows * cols */];  }; /* MatObj 2, column-major; dim0=rows first (byte-confirmed in sub-matrix-list.md; the TIMatrixHdr DB type labels these cols,rows — reversed) */
struct Tokens { uint16_t size;        uint8_t body[/* size */];          }; /* EquObj 3, StrngObj 4, ProgObj 5/6 — tokenized */
struct AppVar { uint16_t size;        uint8_t data[/* size */];          }; /* AppVarObj 0x15 — RAW bytes, not tokenized     */
```

Per object type:

| Type | Val | `dataAddr` → | Size (bytes) |
|------|-----|--------------|--------------|
| `RealObj` | `0` | one `TIFloat` | 9 |
| `CplxObj` | `0x0C` | one `TIComplex` (`re`, `im`) | 18 |
| `ListObj` / `CListObj` | `1` / `0x0D` | `count` word + `count`×`TIFloat`/`TIComplex` | 2 + 9·n / 2 + 18·n |
| `MatObj` | `2` | `rows`,`cols` bytes (`dim0`=rows) + `TIFloat[]`, column-major (index math in [Matrices & Lists](sub-matrix-list.md)) | 2 + 9·r·c |
| `EquObj` | `3` | `size` word + tokenized formula — *system* var, carries a selection/style byte, auto-evaluated ([Graphing](sub-graphing.md), [Table](sub-table-yvars.md)) | 2 + size |
| `StrngObj` | `4` | `size` word + tokenized text — *inert* (see [Strings](#strings-str1str0--a-distinct-object-type-confirmed)) | 2 + size |
| `ProgObj` / `ProtProgObj` | `5` / `6` | `size` word + tokenized program (6 = edit-locked) | 2 + size |
| `AppVarObj` | `0x15` | `size` word + raw bytes (any binary, not tokens) | 2 + size |
| `PictObj` | `7` | a graph back-buffer image (`plotSScreen` snapshot) | 756-byte payload + 2-byte size word = 758 (`_CreatePict` passes payload size `0x02F4`) |
| `GDBObj` | `8` | graph database: mode byte + window vars + selected equations + styles | varies |
| `GroupObj` | `0x17` | an archived bundle of other vars (lives in Flash) | varies |

`WindowObj`/`ZStoObj` (`0x0F`/`0x10`) hold the graph **Window** settings, `TblRngObj` (`0x11`) the table range, `BackupObj` (`0x13`) a full RAM image — all system, fixed-shape blobs.

Aggregate creators size their data region (= count × element-size + 2-byte header) in the `var_alloc` prelude (`ram:1005`), then fall into the common create core (`ram:1011`), which carves the gap via the internal routine at `ram:0F0C` (the create path's own block-move, not the public `_InsertMem`; see [12](12-memory-management.md)). The specific `_Create*` routine then writes the data header after the core returns — e.g. `_CreateRList` writes the list count, `_CreateStrng` the 2-byte size word. All key off the name in `OP1` (`OP1.exp` is the name's token class — `_CreateRList` validates a list-name token `0x5D/0x24/0x3A/0x72`).

## The VAT entry [confirmed — byte-verified vs `findsym_scan`]

The VAT grows downward from `symTable` (`0xFE66`); `_FindSym` (`00:0E65` → `findsym_scan` `07:565F`) scans down, matching the name in `OP1`. Fixed-token names (reals, complex, `L`-lists, `[A]`-matrices, system vars) are matched by a short 1–3 byte compare against `OP1`'s `0x8479`–`0x847B`; length-prefixed names (programs, appvars, groups) branch to a separate name scanner at `07:55D1` that compares the full name. On a match it reads the entry's metadata at fixed offsets relative to the matched name pointer `N`:

| Location (vs name ptr `N`) | Field |
|----------------------------|-------|
| `N`, `N-1`, `N-2` | the name bytes (matched against `OP1`'s `0x8479`–`0x847B`) |
| `N+1` | data page (`B`; `0` ⇒ data in RAM) |
| `N+2` / `N+3` | data address — high byte, then low byte |
| `N+6` | type — low 5 bits = `TIVarType` class, high bits flag archive state; copied to `OP1` at `0x8478` |

Because the VAT grows downward, the type byte sits at the higher address and the name at the lower, so the scanner reads metadata *upward* from the matched name (this is the reverse of a forward C-struct order). `_FindSym`/`_ChkFindSym` return the page in `B` (`0` ⇒ data in RAM). For an archived var the data address points into Flash and the page byte selects the page; the VAT entry itself always stays in RAM (only the data moves to Flash).

Names come in two encodings:

- **Token-named vars** — real, complex, `L`-lists (`tVarLst` `0x5D`), `[A]`-matrices (`tVarMat` `0x5C`), system vars, and the token-named strings (`tVarStrng` `0xAA` + id) and equations (`tVarEqu` `0x5E` + id) — carry a fixed name token, matched by the 1–3 byte compare above.
- **Length-prefixed names** — programs, appvars, groups — store the name bytes with a length byte at the higher address; the scanner at `07:55D1` reads the length byte, then compares the name bytes that precede it (downward, toward lower addresses — the same high-address-first ordering as the rest of the entry).

## Strings (`Str1`–`Str0`) — a distinct object type [confirmed]

String variables are `StrngObj` (type 4) — not equation variables (`EquObj` = 3), although both hold tokenized byte streams. The ten strings `Str1`…`Str0` are named by a 2-byte token: lead `tVarStrng` (`0xAA`) then `tStr1`…`tStr0` (`0x00`…`0x09`), so `Str1` = `AA 00` … `Str0` = `AA 09`.

**Storage.** `_CreateStrng` (id `0x4327`, `00:1123`) decompiles to `create_var_entry(StrngObj)` followed by writing a 2-byte `word size` into the data; the data area is then `[word size][size tokenized bytes]` — the same `[size][bytes]` shape programs and appvars use (above). The bytes are TI-BASIC tokens, not raw ASCII: a string stores exactly the token stream the editor renders, so `"sin(A)"` keeps the `sin(` token, the `A` token, and `)` — which is why a string can hold any displayable token, commands included.

**String vs. equation variable.** Both hold tokenized byte streams, so the two are worth separating. `EquObj` vars (`Y1`–`Y0`, parametric, polar, sequence) are *system* variables that carry a selection/style flags byte and are auto-evaluated by the grapher, table, and solver (see [Graphing](sub-graphing.md), [Table & Y= Variables](sub-table-yvars.md)). A `StrngObj` is an *inert user variable* — no selection/style, never evaluated on its own; it is bytes the string commands manipulate.

**Bridges between the two.** Tokens convert a string's text to/from executable form:
- `expr(` parses a string's token bytes as an expression and evaluates it → a value (string → number/list/…).
- `String►Equ(` / `Equ►String(` (2-byte tokens `BB 56` / `BB 55` — `t2ByteTok` `0xBB` then `tStrngToEqu` `0x56` / `tEquToStrng` `0x55`) copy token bytes between a `Str` and a `Y=`/equation variable (string ↔ equation).
- `sub(`, `length(` (`_StrLength`, id `0x4C3F` → `36:7F91`), and `inString(` operate on the token bytes; `_StrCopy` (`0x44E3` → `00:2810`) is the byte mover. The `"` string-literal delimiter in source is its own token, `tString` (`0x2A`).

## Resolved
The `_FindSym` scan loop and per-class VAT entry layout are byte-verified in [Variables, Archive & Unarchive](sub-vat-archive.md) (`findsym_scan`@`07:565F`; `tSymPtr1`/`tSymPtr2` and archived-var resolution covered there).
