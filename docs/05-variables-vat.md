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

## VAT entry shape — `VATEntry` (modeled) [partly hypothesis]
Working backward from the table top, each record carries: type, version, 2-byte data address, data page (0 = RAM), name length, then the name bytes (stored in reverse). Exact field order varies by object class (named vars vs. list/matrix vs. program) — to be pinned down by tracing `_FindSym`'s scan loop.

## TODO
- Trace `_FindSym` body (it tail-calls the cross-page jumper `FUN_2b09` → real scan loop on another page) and nail the exact `VATEntry` layout per type.
- Map `OP1` name encoding for each object class (e.g. list names prefixed with a token, program names raw).
- Find the symbol-table pointers (`tSymPtr1/2`, `9818/981A`) and how archived (flash) vars are resolved.
