# 05 — Variables & the VAT (Variable Allocation Table)

> **Deep dive:** [Variables, Archive & Unarchive](sub-vat-archive.md) — Store/Recall, the byte-verified `_FindSym` walk, and archive/unarchive.

Every named object the user creates — reals, lists, matrices, strings, programs, pictures, appvars, groups — is catalogued in the **VAT**, a table in RAM that grows *downward* from a fixed top. The VAT stores metadata + where the data lives; the data itself sits elsewhere in RAM (or in archived flash).

## Object types — `TIVarType` enum [confirmed, from ti83plus.inc]

| Val | Name | Val | Name |
|-----|------|-----|------|
| 0 | RealObj | 0x0C | CplxObj |
| 1 | ListObj | 0x0D | CListObj |
| 2 | MatObj | 0x0F | WindowObj |
| 3 | EquObj | 0x10 | ZStoObj |
| 4 | StrngObj | 0x11 | TblRngObj |
| 5 | ProgObj | 0x13 | BackupObj |
| 6 | ProtProgObj | 0x14 | AppObj |
| 7 | PictObj | 0x15 | AppVarObj |
| 8 | GDBObj | 0x16 | TempProgObj |
| | | 0x17 | GroupObj |

The active object's type byte is held in `varType` (`0x85D0`); the current var being processed in `curType` (`0x8450`). Both are typed `TIVarType` in the DB.

## How a variable is named/found

The OS passes variable identity through **`OP1`** as a "name string": `OP1[0]` = type byte, `OP1[1..]` = the name (token/bytes). The lookup/create family all key off OP1:

| Routine | Addr | Role |
|---------|------|------|
| `_FindSym` | `00:0E65` (= **RST 10h**) | find the VAT entry named by OP1; returns ptr/page |
| `_ChkFindSym` | `00:0E60` | type-check OP1 then FindSym (`_CkOP1Real` path) |
| `_CreateReal` | `00:10B8` | make a RealObj named by OP1 |
| `_CreateList`/`Mat`/`Str`/`Prog`/`AppVar`/… | `00:10B0–1153` | one creator per object type |
| `_DelVar`/`_DelVarArc` | `00:1308`/`12D9` | delete (and handle archived copies) |
| `_InsertMem`/`_DelMem` | `00:0F81`/`1368` | low-level grow/shrink of a RAM region (used by create/delete) |

`_CreateReal` (recovered): zeroes `OP1.type`, allocates 9 bytes (`FUN_ram_2045(9)`), handles the complex-list special case (`OP1.exp == 0x5D`), copies the name into the new entry, and on a RAM-full overflow calls `_JError(0x8E)` (`E_Memory`) via the shared body at `00:1011` (`JP C,0x2721 → LD A,0x8E`). A separate `_JError(0x88)` (`E_Syntax`) guards the complex-list named-entry path when the name exceeds 6 characters (`00:1020 CP 0x7; JP NC,0x2700 → LD A,0x88`). The mantissa-byte shuffles are moving the 2-byte data address (`param_2`) and name length into the VAT record fields.

## Variable data formats — rendered as C [confirmed from `_CreateR*` / DB types]

A VAT entry points at the variable's **data**, whose layout depends on the object type. Every numeric value is a 9-byte BCD `TIFloat` (see [Floating-Point](06-floating-point.md)); aggregates are a small header followed by an element array or a tokenized blob. These are the actual DB types (`TIFloat`, `TIComplex`, `TIListHdr`, `TIMatrixHdr`):

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
struct Matrix { uint8_t  rows, cols;  TIFloat elem[/* rows * cols */];  }; /* MatObj 2, stored column-major (rows = dim0) */
struct Tokens { uint16_t size;        uint8_t body[/* size */];          }; /* EquObj 3, StrngObj 4, ProgObj 5/6 — tokenized */
struct AppVar { uint16_t size;        uint8_t data[/* size */];          }; /* AppVarObj 0x15 — RAW bytes, not tokenized     */
```

Per object type:

| Type | Val | `dataAddr` → | Size (bytes) |
|------|-----|--------------|--------------|
| `RealObj` | `0` | one `TIFloat` | 9 |
| `CplxObj` | `0x0C` | one `TIComplex` (`re`, `im`) | 18 |
| `ListObj` / `CListObj` | `1` / `0x0D` | `count` word + `count`×`TIFloat`/`TIComplex` | 2 + 9·n / 2 + 18·n |
| `MatObj` | `2` | `rows`,`cols` bytes (`dim0`=rows) + `TIFloat[]`, **column-major** (index math in [Matrices & Lists](sub-matrix-list.md)) | 2 + 9·r·c |
| `EquObj` | `3` | `size` word + tokenized formula — *system* var, carries a selection/style byte, **auto-evaluated** ([Graphing](sub-graphing.md), [Table](sub-table-yvars.md)) | 2 + size |
| `StrngObj` | `4` | `size` word + tokenized text — *inert* (see [Strings](#strings-str1str0--a-distinct-object-type-confirmed)) | 2 + size |
| `ProgObj` / `ProtProgObj` | `5` / `6` | `size` word + tokenized program (6 = edit-locked) | 2 + size |
| `AppVarObj` | `0x15` | `size` word + **raw** bytes (any binary, not tokens) | 2 + size |
| `PictObj` | `7` | a graph back-buffer image (`plotSScreen` snapshot) | ~768 |
| `GDBObj` | `8` | graph database: mode byte + window vars + selected equations + styles | varies |
| `GroupObj` | `0x17` | an archived bundle of other vars (lives in Flash) | varies |

`WindowObj`/`ZStoObj` (`0x0F`/`0x10`) hold the graph **Window** settings, `TblRngObj` (`0x11`) the table range, `BackupObj` (`0x13`) a full RAM image — all system, fixed-shape blobs.

The common allocator `var_alloc` (`ram:1005`) carves the data region (= count × element-size) via `_InsertMem` (see [12](12-memory-management.md)), then `_CreateXxx` writes the header. All key off the name in `OP1` (`OP1.exp` is the name's token class — `_CreateRList` validates a list-name token `0x5D/0x24/0x3A/0x72`).

## The VAT entry — rendered as C [confirmed — byte-verified vs `findsym_scan` + WikiTI System Table]

The VAT grows **downward** from `symTable` (`0xFE66`); `_FindSym` (`00:0E65` → `findsym_scan` `07:565F`) scans down, matching the name in `OP1`. Each entry is the DB's `VATEntry`:

```c
struct VATEntry {
    uint8_t  type;          /* TIVarType: low 5 bits = class, high bits flag archive state  */
    uint8_t  version;       /* 0 for RAM-created vars; set for some flash/archived vars      */
    uint16_t dataAddr;      /* RAM address of the data — or an offset into Flash if archived */
    uint8_t  dataPage;      /* Flash page holding the data (0 = data is in RAM)              */
    uint8_t  nameLen;       /* length of the name that follows                               */
    uint8_t  name[/* nameLen */];
};
```

Two name encodings share that head:

- **Single-character vars** (real, complex, `L`-lists, `[A]`-matrices, system vars) carry a fixed **2-byte name token + `00`** in place of a length-prefixed string — e.g. list `L₁` = `5D 00`, matrix `[A]` = `5C 00`.
- **Named vars** (programs, appvars, groups, strings, equations) use `nameLen` then that many name bytes.

This is byte-verified against `findsym_scan`: from the matched name token it reads `B = page` at `+1`, the data address at `+2/+3`, and the type at `+6` — matching WikiTI's *System Table* layout. `_FindSym`/`_ChkFindSym` return the **page** in `B` (`0` ⇒ data in RAM). For an **archived** var, `dataAddr` points into Flash and `dataPage` selects the page; the VAT entry itself always stays in RAM (only the data moves to Flash).

## Strings (`Str1`–`Str0`) — a distinct object type [confirmed]

String variables are **`StrngObj` (type 4)** — *not* equation variables (`EquObj` = 3), although both hold tokenized byte streams. The ten strings `Str1`…`Str0` are named by a **2-byte token**: lead `tVarStrng` (`0xAA`) then `tStr1`…`tStr0` (`0x00`…`0x09`), so `Str1` = `AA 00` … `Str0` = `AA 09`.

**Storage.** `_CreateStrng` (id `0x4327`, `00:1123`) decompiles to `create_var_entry(StrngObj)` followed by writing a 2-byte **`word size`** into the data; the data area is then `[word size][size tokenized bytes]` — the same `[size][bytes]` shape programs and appvars use (above). The bytes are **TI-BASIC tokens, not raw ASCII**: a string stores exactly the token stream the editor renders, so `"sin(A)"` keeps the `sin(` token, the `A` token, and `)` — which is why a string can hold any displayable token, commands included.

**String vs. equation variable.** Both hold tokenized byte streams, so the two are worth separating. `EquObj` vars (`Y1`–`Y0`, parametric, polar, sequence) are *system* variables that carry a selection/style flags byte and are **auto-evaluated** by the grapher, table, and solver (see [Graphing](sub-graphing.md), [Table & Y= Variables](sub-table-yvars.md)). A `StrngObj` is an *inert user variable* — no selection/style, never evaluated on its own; it is bytes the string commands manipulate.

**Bridges between the two.** Tokens convert a string's text to/from executable form:
- `expr(` parses a string's token bytes as an expression and **evaluates** it → a value (string → number/list/…).
- `String►Equ(` / `Equ►String(` (token `tStrngToEqu` = `0x56`) copy token bytes between a `Str` and a `Y=`/equation variable (string ↔ equation).
- `sub(`, `length(` (`_StrLength`, id `0x4C3F` → `36:7F91`), and `inString(` operate on the token bytes; `_StrCopy` (`0x44E3` → `00:2810`) is the byte mover. The `"` string-literal delimiter in source is its own token, `tString` (`0x2A`).

## Resolved
The `_FindSym` scan loop and per-class VAT entry layout are byte-verified in [Variables, Archive & Unarchive](sub-vat-archive.md) (`findsym_scan`@`07:565F`; `tSymPtr1`/`tSymPtr2` and archived-var resolution covered there).
