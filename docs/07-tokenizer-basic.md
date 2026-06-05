# 07 — Tokenizer & TI-BASIC

TI-BASIC programs are not stored as text — every command, function, and variable is a **token**. A token is 1 or 2 bytes. The OS *detokenizes* (token→display string) to show a program and *tokenizes* (keypress/text→token) on entry; the **parser** walks tokens to execute.

## Token encoding [confirmed]

- Most tokens are **one byte** (`tStore`=0x04, `tBoxPlot`=0x05, operators, digits, letters, common commands). Modeled as the `TIToken` enum (608 members from `ti83plus.inc`).
- Some bytes are **lead bytes** of a **two-byte token**: the first byte selects a *table*, the second byte the entry.

### The 2-byte lead-byte set [confirmed]

`_IsA2ByteTok` (`00:1FE8`) scans an 11-byte table at `ram:1FF6` to decide if a byte starts a 2-byte token. The bytes are:

| Byte | Meaning (.inc) |
|------|----------------|
| `5C` | `tVarMat` — matrix name (`[A]`…) |
| `5D` | `tVarLst` — list name (`L1`…) |
| `5E` | equation/var-out token group |
| `60` | `tVarPict` — picture |
| `61` | `tVarGDB` — graph database |
| `62` | `tVarOut` — Y-vars / output |
| `63` | `tVarSys` — system var group (Xmin, …) |
| `7E` | graph-format token group |
| `BB` | `t2ByteTok` — the general "extended commands" page (2.x additions) |
| `AA` | `tVarStrng` — string variable (`Str1`…) |
| `EF` | TI-84+-era extended token page |

So e.g. `5D 00` = list `L1`; `BB xx` = an extended command. The second byte indexes that group's name/handler table.

## Detokenize / token length [confirmed]
- `_GetTokLen` (`01:66E5`) returns 1 or 2 for the token at HL (via helper `FUN_page_01_6702`).
- `_Get_Tok_Strng` (`01:66EA`) returns the display string for a token (used by the program editor and `Disp`).

## Parser / interpreter [located — page 0x38]

The expression parser/evaluator lives on **flash page 0x38**. Entry points:
- `_ParseInp` (`38:5987`) — parse/evaluate the input (homescreen/entry line). It calls `parse_init` (`38:5b7b`) to reset parser state, clears editing flags, then resolves via `_ChkFindSym`. **[confirmed]**
- `_Find_Parse_Formula` (`38:758A`) — `_FindSym` a variable then parse its stored formula (Y-vars, equations). **[confirmed]**
- `parse_init` (`38:5b7b`) — zeroes the parse-position/state bytes and clears a batch of parser flag bits (in the IY flag area). **[confirmed]**

The engine reads the token stream and dispatches each token to a handler; arithmetic tokens flow into the FP engine (`06`), variable tokens resolve via the VAT (`05`), and the busy indicator is driven by `_RunIndicOn`/`Off`. `_BinOPExec` applies a binary operator via OP1/OP2.

### The handler dispatch table [confirmed]

Page 0x38 **begins** with the parser's handler-address table at **`page_38:4000`** — **84 entries**, each a 2-byte pointer to a handler routine on page 0x38 (`tools/ParserTable.java` defines it; 81 handlers were disassembled from it). The evaluator indexes this table (`base + class*2`) and `jp (hl)` into the handler.

These handlers implement TI-BASIC **statements/commands and operators**. Sampling them by the routine they call:
- indices 8–10, 17–19, 38 → `bcall(_Regraph)` — **graph commands** (`DrawF`, `ZoomFit`, etc.).
- indices 14–16, 21–22 → `bcall(_Disp)` — **display/output commands** (`Disp`, `Output`).
- the "no-bcall" handlers are the **arithmetic/operator** productions — they drive OP1/OP2 through the FP engine via the **RST shortcuts** (RST 30h `_FPAdd`, etc.), which is why a bcall scan doesn't flag them; variable handlers go through `_FindSym` (`05`).

The first handlers: `page_38:419F, 45F0, 421C, …`.

**TODO (deep dive):** map each table index → its token class/operator (by tracing the index computation), and document the operator-precedence / argument-count handling.

## TODO
- Find the main parser loop (the token-dispatch jump table) and name handlers.
- Map each 2-byte group's second-byte table (esp. `BB` extended commands and `63` system vars).
- Document `OP1`-as-name handoff from a variable token to `_FindSym`.
