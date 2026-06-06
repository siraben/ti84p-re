# 07 — Tokenizer & TI-BASIC

TI-BASIC programs are stored as **tokens**, not text: every command, function, and variable is a token of 1 or 2 bytes. The OS *detokenizes* (token→display string) to show a program and *tokenizes* (keypress/text→token) on entry; the **parser** walks tokens to execute.

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

So e.g. `5D 00` = list `L1`; `BB xx` = an extended command. The second byte indexes that group's name/handler table. (String variables `Str1`–`Str0` use lead `AA`; they are a **distinct VAT object type** holding tokenized text — see [Strings](05-variables-vat.md#strings-str1str0--a-distinct-object-type-confirmed).)

## Detokenize / token length [confirmed]
- `_GetTokLen` (`01:66E5`) returns 1 or 2 for the token at HL (via helper `smallfont_glyph_ptr` (`01:6702`)).
- `_Get_Tok_Strng` (`01:66EA`) returns the display string for a token (used by the program editor and `Disp`).

## Parser / interpreter [located — page 0x38]

The expression parser/evaluator lives on **flash page 0x38**. Entry points:
- `_ParseInp` (`38:5987`) — parse/evaluate the input (homescreen/entry line). It calls `parse_init` (`38:5b7b`) to reset parser state, clears editing flags, then resolves via `_ChkFindSym`. **[confirmed]**
- `_Find_Parse_Formula` (`38:758A`) — `_FindSym` a variable then parse its stored formula (Y-vars, equations). **[confirmed]**
- `parse_init` (`38:5b7b`) — zeroes the parse-position/state bytes and clears a batch of parser flag bits (in the IY flag area). **[confirmed]**

The engine reads the token stream and dispatches each token to a handler; arithmetic tokens flow into the FP engine ([06](06-floating-point.md)), variable tokens resolve via the VAT ([05](05-variables-vat.md)), and the busy indicator is driven by `_RunIndicOn`/`Off`. `_BinOPExec` applies a binary operator via OP1/OP2.

### The handler dispatch table [confirmed]

Page 0x38 **begins** with the parser's handler dispatch at **`page_38:4000`**. This region is **executable dispatch code**, not a flat pointer array (see [TI-BASIC Programs](sub-tibasic.md)).

These handlers implement TI-BASIC **statements/commands and operators**. Sampling them by the routine they call:
- indices 8–10, 17–19, 38 → `bcall(_Regraph)` — **graph commands** (`DrawF`, `ZoomFit`, etc.).
- indices 14–16, 21–22 → `bcall(_Disp)` — **display/output commands** (`Disp`, `Output`).
- the "no-bcall" handlers are the **arithmetic/operator** productions — they drive OP1/OP2 through the FP engine via the **RST shortcuts** (RST 30h `_FPAdd`, etc.), which is why a bcall scan doesn't flag them; variable handlers go through `_FindSym` ([05](05-variables-vat.md)).

The first handlers: `page_38:419F, 45F0, 421C, …`.

### Parse-stream cursor [confirmed]

The evaluator walks the token stream via a cursor in RAM: `parsePtr` (`0x965D` = official `nextParseByte`, current position) and `parseEnd` (`0x965F` = `basic_end`, end). Named helpers on page 0x38:
- `parse_cur_tok` (`38:72DA`) — fetch the token at the cursor.
- `parse_advance` (`38:7248`) — `parsePtr++` and bounds-check vs `parseEnd`.
- `parse_expect_or_err` (`38:5CD8`) — fetch a token and raise `_ErrSyntax` (recording the position in `parsePtr`) if it isn't the expected one.

So the dispatch loop is: `parse_cur_tok` → jump into the dispatch code at `page_38:4000` → run handler (which may consume args via `parse_advance`) → repeat.

**Main evaluator:** `parse_eval_expr` (`38:5AB3`) is the big recursive-descent expression evaluator — it dispatches through handler function-pointers (`code *`) with operator precedence, reading via the cursor helpers and leaving the result in `OP1`. `_ParseInp` → `parse_init` → `parse_eval_expr`. `parse_scan_tokens` (`38:4180`) is a token-scan helper (skips to a delimiter, honoring 2-byte tokens via `_IsA2ByteTok`).

The region at `page_38:4000` is **executable dispatch code** (sequences like `CALL 0x33AB; …`), not a flat array of 2-byte handler pointers. The dispatch is table-like in effect, but it's code. See [sub-tibasic.md](sub-tibasic.md) for the execution model (`eval_stmt_entry`@`38:59C5`, the `blockmatch_end_else`@`38:4130` End/Else matcher, `goto_lbl_name_scanner`@`38:4870`).

The handlers are **recursive-descent grammar productions** (not flat per-operator routines): each reads via `parse_cur_tok`, conditionally recurses, and some load **sub-dispatch tables** (e.g. `page_38:5110`, `5127`) for finer token classes — implementing operator precedence by nesting. So "the + operator" isn't one table entry; it's handled within the term/factor production that drives `_FPAdd` (RST 30h).

The precedence levels (term/factor/unary productions) and sub-dispatch tables are mapped in [TI-BASIC Programs](sub-tibasic.md) §3/§6.

## Second-byte tables

Every 2-byte token group's second-byte → token mapping (matrices, lists, Y-vars, system/window vars, the `BB` extended-command page, the `EF` 84+ page, etc.) is tabulated in **[2-Byte Token Tables](token-tables.md)** — 492 tokens, sourced from [TI-Toolkit/tokens](https://github.com/TI-Toolkit/tokens) and filtered to the 84+ 2.55MP.

(The main parser loop, handler dispatch, and `OP1`-as-name handoff are covered in [TI-BASIC Programs](sub-tibasic.md).)
