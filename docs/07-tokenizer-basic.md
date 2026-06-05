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

## Parser / interpreter [in progress]
The execution engine (on banked pages) reads the program token stream and dispatches each token to a handler. Relevant bcalls seen: `_BinOPExec` (apply a binary operator using OP1/OP2), `_RunIndicOn`/`_RunIndicOff` (the busy indicator during execution), `_NextTok`/`_EOS`-style stream helpers. Arithmetic tokens flow into the FP engine (`06-floating-point.md`); variable tokens resolve via the VAT (`05-variables-vat.md`).

## TODO
- Find the main parser loop (the token-dispatch jump table) and name handlers.
- Map each 2-byte group's second-byte table (esp. `BB` extended commands and `63` system vars).
- Document `OP1`-as-name handoff from a variable token to `_FindSym`.
