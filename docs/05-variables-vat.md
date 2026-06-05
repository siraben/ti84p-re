# 05 — Variables & the VAT (Variable Allocation Table)

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

`_CreateReal` (recovered): zeroes `OP1.type`, allocates 9 bytes (`FUN_ram_2045(9)`), handles the complex-list special case (`OP1.exp == 0x5D`), copies the name into the new entry, and on overflow calls `_JError(0x88)` (`E_Memory`-class). The mantissa-byte shuffles are moving the 2-byte data address (`param_2`) and name length into the VAT record fields.

## Variable data layouts [confirmed from `_CreateR*`]

The VAT entry points at the variable's **data**, whose format depends on the object type:

| Type | Data layout |
|------|-------------|
| Real / Complex | `TIFloat` (9 bytes) / two floats (18) |
| **List** (`_CreateRList`) | `word count` then `count × TIFloat`. A flag byte = `0x0C` marks a **complex** list (18-byte elements). |
| **Matrix** (`_CreateRMat`) | `byte cols; byte rows;` then `rows*cols × TIFloat`, **column-major** (`_HTimesL` computes the element count). |
| String / Program / AppVar | `word size` then `size` raw/tokenized bytes |

The common allocator `var_alloc` (`ram:1005`) carves the data region (size = count × element-size) via `_InsertMem` (see `12`), then the `_CreateXxx` routine writes the header. All key off the name in `OP1` (`OP1.exp` carries the name's token class — `_CreateRList` validates it's a list-name token `0x5D/0x24/0x3A/0x72`).

## VAT entry shape [standard TI-83+ format]

`_FindSym` (`00:0E65` → `findsym_scan` `page_07:565F`) walks the VAT from `symTable` (`0xFE66`) **downward**, matching the name passed in `OP1`. Each entry is stored high-address-first; the format depends on the object class:

**Single-character vars** (real, complex, `Ln` lists, `[A]` matrices, system vars — 5 bytes):
```
typeID      ; TIVarType
typeID2     ; mirror of typeID (flags in high nibble)
addrLSB     ; data address (RAM) low
addrMSB     ;                    high
nameToken   ; the 1-byte name token (e.g. the var letter / list token)
```

**Named vars** (programs, appvars, groups, strings, equations — variable length):
```
typeID
version     ; usually 0 (nonzero for some appvars)
addrLSB
addrMSB
nameLen     ; N
name[0..N-1]; name bytes
```

For **archived** vars the data address points into Flash and a page byte selects the Flash page (the in-RAM VAT entry still lives in RAM; only the data is in Flash). The `findsym_scan` body decompiles messily (inline bjumps), so this layout is the documented TI-83+ format — consistent with the header writes seen in `_CreateRList`/`_CreateRMat`. The `VATEntry` struct in the DB models the named-var case.

## TODO
- Trace `_FindSym` body (it tail-calls the cross-page jumper `FUN_2b09` → real scan loop on another page) and nail the exact `VATEntry` layout per type.
- Map `OP1` name encoding for each object class (e.g. list names prefixed with a token, program names raw).
- Find the symbol-table pointers (`tSymPtr1/2`, `9818/981A`) and how archived (flash) vars are resolved.
