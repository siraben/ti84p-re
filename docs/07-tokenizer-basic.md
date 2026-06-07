# 07 — Tokenizer & TI-BASIC

TI-BASIC programs are stored as **tokens**, not text: every command, function, and variable is a token of 1 or 2 bytes. The OS *detokenizes* (token→display string) to show a program and *tokenizes* (keypress/text→token) on entry; the **parser** walks tokens to execute.

## Token encoding [confirmed]

- Most tokens are **one byte** (`tStore`=0x04, `tBoxPlot`=0x05, operators, digits, letters, common commands). Modeled as the `TIToken` enum, which carries 608 members as built into the current Ghidra database from the `t`-prefixed equates of `ti83plus.inc`.
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

Page 0x38 **begins** with the parser's handler dispatch at **`page_38:4000`** — a **flat array of 2-byte little-endian handler pointers**. Raw bytes are `9F 41 F0 45 1C 42 …` = entries `0x419F, 0x45F0, 0x421C, …` (all in-window `0x4xxx`/`0x47xx` code addresses), indexed by token class and dereferenced; the selector at `38:7010` loads `LD HL,0x4000` and adds `2×index` (see [TI-BASIC Programs](sub-tibasic.md)).

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

So the dispatch loop is: `parse_cur_tok` → index the pointer table at `page_38:4000` and call the selected handler (which may consume args via `parse_advance`) → repeat.

**Main evaluator:** `parse_eval_expr` (`38:5AB3`) is the big recursive-descent expression evaluator — it dispatches through handler function-pointers (`code *`) with operator precedence, reading via the cursor helpers and leaving the result in `OP1`. `_ParseInp` → `parse_init` → `parse_eval_expr`. `parse_scan_tokens` (`38:4180`) is a token-scan helper (skips to a delimiter, honoring 2-byte tokens via `_IsA2ByteTok`).

The region at `page_38:4000` is a **flat array of 2-byte handler pointers** (entries `0x419F, 0x45F0, 0x421C, …`), not executable code — `CALL 0x33AB` (`CD AB 33`) appears nowhere on page 0x38. Each handler is itself recursive-descent code; the table selects which one to enter. See [sub-tibasic.md](sub-tibasic.md) for the execution model (`eval_stmt_entry`@`38:59C5`, the `blockmatch_end_else`@`38:4130` End/Else matcher, `goto_lbl_name_scanner`@`38:4870`).

The handlers are **recursive-descent grammar productions** (not flat per-operator routines): each reads via `parse_cur_tok`, conditionally recurses, and some load **sub-dispatch tables** (e.g. `page_38:5110`, `5127`) for finer token classes — implementing operator precedence by nesting. So "the + operator" isn't one table entry; it's handled within the term/factor production that drives `_FPAdd` (RST 30h).

The precedence levels (term/factor/unary productions) and sub-dispatch tables are mapped in [TI-BASIC Programs](sub-tibasic.md) §3/§6.

## Tokenized sample programs

The raw bodies below are the bytes stored after a `ProgObj` size word. They can
be regenerated, along with loadable `.8xp` files, with
[`tools/tibasic_samples.py`](../tools/tibasic_samples.py) `--write-dir
tools/tibasic-samples` and traced with the workflow in
[`tools/dynamic-tracing.md`](../tools/dynamic-tracing.md). The generated samples
were run under headless TilEm on OS 2.55MP; see
[TI-BASIC programs](sub-tibasic.md#dynamic-confirmation-and-traceable-examples)
for observed outputs and trace anchors.

| Program | Source | Body bytes |
|---------|--------|------------|
| Hello | `ClrHome` / `Disp "HELLO, WORLD"` | `E1 3F DE 2A 48 45 4C 4C 4F 2B 29 57 4F 52 4C 44 2A 3F` |
| Factorial | `Prompt N` / `1->F` / `For(I,1,N)` / `F*I->F` / `End` / `Disp F` | `DD 4E 3F 31 04 46 3F D3 49 2B 31 2B 4E 11 3F 46 82 49 04 46 3F D4 3F DE 46 3F` |
| Data | `{3,1,4,1,5}->L1` / `SortA(L1)` / `cumSum(L1)->L2` / `sum(L1)->S` / display results | `08 33 2B 31 2B 34 2B 31 2B 35 09 04 5D 00 3F E3 5D 00 11 3F BB 29 5D 00 11 04 5D 01 3F B6 5D 00 11 04 53 3F DE 5D 00 3F DE 5D 01 3F DE 53 3F` |
| `Asm(` wrapper | `Disp "BEFORE"` / `Asm(prgmASMRET)` / `Disp "AFTER"` | `DE 2A 42 45 46 4F 52 45 2A 3F BB 6A 5F 41 53 4D 52 45 54 11 3F DE 2A 41 46 54 45 52 2A 3F` |

These examples show the main token categories the parser must walk:
statement separators (`3F`), string delimiters (`2A`), store (`04`), list names
(`5D 00`/`5D 01`), extended `BB` tokens (`cumSum(` = `BB 29`, `Asm(` = `BB 6A`,
`AsmPrgm` = `BB 6C`), and command tokens such as `Prompt` (`DD`), `Disp` (`DE`),
`For(` (`D3`), `End` (`D4`), `ClrHome` (`E1`), and `SortA(` (`E3`). The
`Asm(prgmASMRET)` wrapper also shows the program-name token (`5F`) before the
name characters. [confirmed token bytes from `ti83plus.inc` and
`token-tables.md`]

## Second-byte tables

Every 2-byte token group's second-byte → token mapping (matrices, lists, Y-vars, system/window vars, the `BB` extended-command page, the `EF` 84+ page, etc.) is tabulated in **[2-Byte Token Tables](token-tables.md)** — 492 tokens, sourced from [TI-Toolkit/tokens](https://github.com/TI-Toolkit/tokens) and filtered to the 84+ 2.55MP.

(The main parser loop, handler dispatch, and `OP1`-as-name handoff are covered in [TI-BASIC Programs](sub-tibasic.md).)
