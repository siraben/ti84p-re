# TI-BASIC Programs

*TI-84 Plus OS 2.55MP — feature deep dive.*

How a student-written TI-BASIC program is stored, parsed, and executed on OS
2.55MP. Builds on [07-tokenizer-basic.md](07-tokenizer-basic.md) (tokens, cursor helpers, the page-0x38
evaluator), [05-variables-vat.md](05-variables-vat.md) (OP1 naming, `_FindSym`), and
[11-boot-contexts-errors.md](11-boot-contexts-errors.md) (contexts, `onSP`/`_JError`).

Confidence: **[confirmed]** = decompiled/byte-verified here; **[strong]** =
multiple consistent signals (token compares, call shape) but the dense Z80
handler bodies don't fully reduce in the decompiler; **[inferred]** = standard
TI-83+/84+ behavior consistent with what was seen.

---

## 1. How a program is stored [confirmed]

A program is a VAT object of type `ProgObj` (5) / `ProtProgObj` (6) (see doc 05).
Its data is `word size` followed by `size` bytes of **tokenized** body — the
exact byte stream the parser walks. No line numbers; lines are separated by the
**EOL/newline token `0x3F`** (`tEnter`, shown as `cVar=='?'` = 0x3F in the
decompiled cursor code). Most tokens are 1 byte; the 11 lead bytes
(`5C 5D 5E 60 61 62 63 7E AA BB EF`) introduce 2-byte tokens (doc 07).

Editing/detokenizing for the program editor uses the page-01 token helpers
(doc 07, re-confirmed here):
- `_GetTokLen` (`01:66E5`) — returns 1 or 2 for the token at HL (length of the
  token's byte encoding), via `FUN_page_01_6702`.
- `_Get_Tok_Strng` (`01:66EA`) — returns the display string for a token
  (cross-page jump to the name table). The editor calls this per token to paint
  a line; `Disp` of a list/string also routes display text through related
  formatters.

---

## 2. The parse-stream cursor [confirmed]

The interpreter walks the token body through a RAM cursor (doc 07, all
re-verified by decompilation):

| Helper | Addr | Behavior |
|--------|------|----------|
| `parse_cur_tok` | `38:72DA` | fetch token at cursor (`parsePtr`); special-cases EOL `0x3F`/end `0x00` |
| `parse_advance` | `38:7248` | `parsePtr (DAT_ram_965d)++`, bounds-check vs `parseEnd (DAT_ram_965f)`; refill via `FUN_38_5b79` |
| `parse_expect_or_err` | `38:5CD8` | fetch a token; if not the expected one, set `parsePtr` to the fault position and `_ErrSyntax` |
| `parse_scan_tokens` | `38:4180` | skip forward to a delimiter, honoring 2-byte tokens via `_IsA2ByteTok`; used by every block scanner |
| `parse_init` | `38:5B7B` | zero parse position bytes (+6/+7), clear a batch of parser flag bits in the IY flag area |

`parsePtr` = `DAT_ram_965d`, `parseEnd` = `DAT_ram_965f`. `parse_scan_tokens`
loop: `parse_cur_tok`; if token==EOL(`0x2A`-class delimiter in its local test)
stop, else `_IsA2ByteTok` then `parse_advance` (twice for a 2-byte token). This
is the primitive every control-flow scanner is built on.

---

## 3. Top-level execution model [confirmed / strong]

- `_ParseInp` (`38:5987`) is the entry that parses/evaluates the entry line or a
  formula: it clears `DAT_ram_9305`, calls `parse_init`, clears an editing flag
  (`*(IY+0x1F) &= 0xF7`), then tail-calls `_ChkFindSym` to resolve OP1.
  **[confirmed]**
- `_Find_Parse_Formula` (`38:758A`) `_FindSym`s a named var then parses its
  stored formula; its body switches on var type (`0x0F` Window / `0x10` ZSto /
  `0x11` TblRng special-cased) before the cross-page parse. Used for Y-vars /
  equations and for **running a program** (resolve ProgObj, point the cursor at
  its body, run the statement loop). **[confirmed header, strong for prog-run]**
- The **statement/expression evaluator** is the big recursive-descent core
  `parse_eval_expr` (`38:5AB3`). The interpreter has **several entry variants**
  that all converge on the same shared inner loop (label `LAB_38_59c8`) and the
  same precedence selector (`LAB_38_7010`): `38:59C5`, `38:5826`, `38:5CA7`,
  `38:6963`, `38:6F63`. Each variant does statement-type-specific setup/teardown
  (FPS push, flag bits) and then runs the common token loop. **[confirmed]**

### The shared inner loop (`LAB_38_59c8`) [confirmed]

```
loop:
  FUN_38_7245 / FUN_ram_1fd6     ; refresh cursor / housekeeping
  class = FUN_38_72e0()          ; classify current token
  if (IY+9 & 0x80) class = FUN_ram_20a0()   ; alt classify for flagged tokens
  IY+9 &= 0x7F
  if class == 4: parse_pos=fault; _ErrSyntax     ; class 4 = syntax error
  if class <= 3:                 ; an operand/sub-expression
       cls = FUN_38_70f8()       ; map token -> grammar class (>0xF1 => +0x12)
       precLevel = 3
  LAB_7010:                      ; dispatch by precedence level
       if precLevel==2: handler = FUN_38_478c   ; postfix/factorial+power production
       if precLevel==3: handler = FUN_38_7175   ; (nop / leaf)
       else:            handler = 0x4000        ; the base dispatch block
       ... call handler, fold result via FP RSTs into OP1 ...
```

The `param_2`/handler pointer is one of `0x4000` (base/term), `0x478c`
(`FUN_38_478c`, the **postfix `^`/`!` production** — it reads `+`/`^` (0x11),
range-checks an exponent as a positive int, `_JError(0x84)` Domain otherwise),
or `0x7175` (a leaf no-op). Selecting among these by `precLevel` (1/2/3) is how
operator **precedence** is realized — nesting of productions, not a flat table
(confirms doc 07's "recursive-descent" claim). Results land in **OP1**; binary
operators are applied via the FP RST shortcuts (RST 30h `_FPAdd`, …) and
`_BinOPExec`.

### `page_38:4000` is code, not a flat pointer table [confirmed — corrects doc 07]

Raw bytes at `38:4000` are `CD AB 33 CD 78 1A 21 50 8F …` = `CALL 0x33AB;
CALL 0x1A78; LD HL,0x8F50; …` — i.e. **executable dispatch code**, the "base
production" the evaluator jumps into (`handler = 0x4000`), not an array of
84 two-byte handler pointers. The earlier `ParserTable.java` count came from
mis-reading this code as pointers. The real dispatch is the
`FUN_38_72e0`/`FUN_38_70f8` classify + `LAB_7010` precedence selector above.

### Results / Ans [confirmed]

- `_StoAns` (`38:6251`) stores OP1 into `Ans` (`_CkOP1Real` path; the bytes that
  follow are the Ans-var token table). `_RclAns` (`38:679F`) = `_AnsName` then
  `_RclVarSym`.
- `_AnsName` (`38:74B7`): `_ZeroOP1; OP1.exp = 0x72` — builds the OP1 name for
  the `Ans` variable (token class `0x72`).
- `_StoSysTok`/`_RclSysTok` (`38:623B`/`683E`) store/recall a system token
  variable (Xmin etc.) into/from OP1.

---

## 4. Control flow [confirmed core, strong details]

Control-flow tokens (`ti83plus.inc`): `tIf=CE tThen=CF tElse=D0 tWhile=D1
tRepeat=D2 tFor=D3 tEnd=D4 tReturn=D5 tLbl=D6 tGoto=D7 tPause=D8 tStop=D9`.

### Block matcher / End-Else scanner: `FUN_38_4130` [confirmed]

This is the routine that **skips a block to its matching `End`/`Else`** (used to
skip the not-taken branch of `If` / `If…Then`, and to bound `For`/`While`/
`Repeat` bodies). It keeps a nest-depth counter and walks via
`parse_scan_tokens`:

```
depth = 0
loop:
  t = cur_token
  case t == tElse(D0):  if depth==0 -> stop, return 0xD0 (Else)   ; else skip
  case t == tEnd (D4):  if depth==0 -> stop, return 0xD4 (End)
                        else depth--                              ; close a nest
  case t in {tFor(D3), tWhile(D1), tRepeat(D2)}: depth++          ; open a nest
  case t == tIf (CE):   scan; if next == tThen(CF) depth++        ; If…Then opens
  default: parse_scan_tokens (skip token, honoring 2-byte)
```

Token compares verified at `38:4137 (CP D0)`, `414B (CP D4)`, `415D (CP D3)`,
`4164 (CP D1)`, `4168 (CP D2)`, `416C (CP CE)`, `4179/41B3 (CP CF)`. Return
value 0xD0 vs 0xD4 tells the caller whether it landed on `Else` or `End`.

### If / Then / Else execution [strong]

- The `If` statement handler evaluates the condition into OP1 (real). If the
  next token is **not** `tThen`, it's a single-statement `If` (execute the one
  statement when true, skip it when false). If `tThen`, it's a block.
- The **Else** path is `FUN_38_5826`: on seeing `tElse(D0)` it repeatedly calls
  the block matcher `FUN_38_4130` to **skip the Else block to its matching End**
  (the "condition was true, ran Then, now jump over Else" case), then rejoins the
  shared loop at `LAB_38_59c8`. Other `tElse` compares at `38:57B3/58A6/58C6`
  handle the symmetric "skip Then, run Else" and nested cases.
- `FUN_38_6F63` is the per-statement entry that special-cases `tIf(CE)` and
  `tStop(DA-region)`: for `tIf` it sets grammar class `0x5F` and falls into the
  shared precedence loop to evaluate the condition; unknown leading tokens here
  raise `_JError(0x88)` (illegal) or `_JError(0x30)` (syntax). **[confirmed
  bytes]**

### For( / While / Repeat / End [strong]

- `For(`/`While`/`Repeat` push a **loop-control record onto the FPS/loop stack**
  recording the loop variable, limit, step, and the `parsePtr` of the loop top
  (so `End` can jump back). `End` pops/updates: increments the `For` variable,
  re-tests the limit, and either re-seeds `parsePtr` to the loop top or falls
  through. The block matcher `FUN_38_4130` is what bounds these bodies during
  skips (e.g. `While 0` skips straight to `End`).
- `FUN_38_5826`'s prologue calls `_DeallocFPS1` then `FUN_38_58df` (which sets
  `pTempCnt`/`cleanTmp`) — FPS bookkeeping consistent with pushing/popping a loop
  frame. **[strong]**

### Goto / Lbl: `FUN_38_4870` + scanner at `38:7600` [confirmed]

- `Lbl`/`Goto` use a name scanner. `FUN_38_4870` reads the label name after
  `tGoto(D7)`/`tLbl(D6)`: it advances over the (possibly 2-byte) label token(s)
  until EOL (`'?'`=0x3F) / end, records the position in `parsePtr`, then does a
  `cross_page_jump(0x14)` to the search routine. Token compares for `tLbl(D6)` at
  `38:4870` and `38:7626`; `tGoto(D7)` at `38:762A`. **[confirmed]**
- `Goto` resolves by **rescanning the program body from the top** for a matching
  `Lbl name`, then setting `parsePtr` there — the classic TI-BASIC behavior that
  makes `Goto` O(program size) and makes `Goto` out of a loop leak the loop's
  stack frame. **[inferred — standard, consistent with the rescan call shape]**
- `Return`/`Stop` (`tReturn=D5`/`tStop=D9`) terminate the current program /
  unwind: they exit the statement loop back to the caller (or to the homescreen
  context via the `onSP`/context mechanism in doc 11). **[inferred/strong]**

---

## 5. I/O commands

The **display primitives** live on pages 01/04/37; the **command (token)
handlers** that parse arguments live mostly on **page 0x02** (the TI-BASIC
command-execution page) and **page 0x39**, reached from the page-38 evaluator via
cross-page jump (`RST2`/bjump). Token-compare sites located by ROM scan:

| Command | Token | Handler site(s) | Display primitive used |
|---------|-------|-----------------|------------------------|
| `Disp` | `tDisp=DE` | dispatch → `_Disp` (`37:51D3`), bcall site `38:45A4` | `_Disp`, `_NewLine`, `_DispDone` |
| `Output(` | `tOutput=E0` | `38:6AE6` (CP E0), `02:673E`, `01:7D3D` | `_OutputExpr` (`03:4AF2`) at row,col |
| `Input` | `tInput=DC` | `02:54EF`, `02:56AB`, `02:5917`, `01:7DEF` | prompt + entry-line editor + `_ParseInp` of typed text |
| `Prompt` | `tPrompt=DD` | `02:562F`, `02:5786`, `02:590E`, `00:4C5C` | like `Input` but auto-labels `NAME=?` |
| `Menu(` | `tMenu=E6` | `38:5A8A` (CP E6), `02:555D`, `06:4A17` | `_DispMenuTitle` (`39:4D21`) + branch on choice |
| `Pause` | `tPause=D8` | `02:55E7`, `02:6684`, `39:6B8E`, `3A:7E7C` | display then wait for `[ENTER]` via key loop |
| `getKey` | `tGetKey=AD` | `37:6700` (keymap), `3A:7E8A` | non-blocking `_GetKey`; returns keycode→OP1 |
| `ClrHome` | (cmd token) | clears text shadow + home cursor | `_ClrLCDFull` / home-cursor reset |

Details:

- **`Disp` / `Disp expr`** — `_Disp` (`37:51D3`): sets a "text in display" flag
  (`IY+0x0D |= 4`), and when the active context is the home/run context
  (`cxCurApp == 'D'`) it clears graph-style state and cross-page-jumps into the
  paint routine; otherwise `RST5` (bjump) to the generic display path. Numeric
  results format via `_DispOP1A` (`04:7844`) → `_CkOP1Real`; strings/lists route
  through their formatters. Each `Disp` item ends with `_NewLine` (`01:5F4A`):
  `curCol=0`, and if `curRow+1 >= winBtm` it triggers scroll, else `curRow++`.
  `_DispDone` (`01:69B0`) finishes. **[confirmed for `_Disp`/`_NewLine`]**
- **`Output(row,col,value`** — `_OutputExpr` (`03:4AF2`, cross-page) writes at an
  absolute (row,col) without scrolling. Handler parses three comma-separated
  args, range-checks row/col, then calls it. **[strong]**
- **`Input` / `Prompt`** — these handlers (page 02) drop into the **entry-line
  editor**: show the prompt (`?` for `Input`, `VAR=` for `Prompt`), let the user
  type, tokenize the input, and feed it back through the parser (`_ParseInp`) to
  store into the target variable. `Prompt` loops over a comma list of variables,
  auto-printing each variable's name. **[strong — token sites confirmed; bodies
  dense]**
- **`Menu(`** — `_DispMenuTitle` (`39:4D21`) draws the title; the handler stores
  branch-target `Lbl`s, draws up to 7 options, blocks for a key, and on selection
  performs a `Goto`-style jump to the chosen `Lbl`. Token site `38:5A8A`. **[strong]**
- **`Pause`** — displays (optionally an expression), then spins in a key-read
  loop until `[ENTER]`; `Pause expr,N` (2.55MP) scrolls a list/matrix. Sites at
  `02:55E7`, `39:6B8E`. **[strong]**
- **`getKey`** — non-blocking: reads the current key and returns its code in OP1
  (0 if none). Used as a value inside expressions, so it's wired as an operand
  token (`tGetKey=AD`) in the evaluator, not a statement. **[strong]**
- **`ClrHome`** — clears the home-screen text shadow and resets the cursor to
  (0,0). **[inferred — standard]**

The **`_RunIndicOn`/`Off`** (`01:6518`/`6531`) busy indicator runs during
execution: `_RunIndicOn` sets `indicBusy=0xF0`, `indicCounter=1`, enables
interrupts, sets `IY+0x12 |= 1`. The interpreter turns it on while a program
runs and off at `Done`. **[confirmed]**

---

## 6. Token dispatch & precedence — summary [confirmed]

1. `parse_cur_tok` fetches a token at `parsePtr`.
2. `FUN_38_72e0` classifies it into a small class number (`<=3` operand/expr,
   `4` = syntax error, others = operator/command). Flagged tokens reclassify via
   `FUN_ram_20a0` when `IY+9 & 0x80`.
3. `FUN_38_70f8` maps the token byte to a grammar/precedence class (tokens
   `>0xF1` get `+0x12`, folding the high token page into the class space).
4. The precedence level (`cVar4` = 1/2/3) selects the production handler:
   `0x4000` (base term/dispatch), `FUN_38_478c` (postfix `^`/`!`), or
   `FUN_38_7175` (leaf). Nesting these realizes precedence.
5. Binary ops fold operands via FP RSTs (RST 30h `_FPAdd`; `_FPMult`=`00:238B`, …)
   / `_BinOPExec`, leaving the result in **OP1**.
6. Variable tokens become an OP1 name (type byte + name) and resolve via
   `_FindSym`/`_RclVarSym` (doc 05); store targets (`→VAR`) resolve through the
   `38:7600` name scanner (handles `[A]`/`L1`/`Str1`/Y-var/`Ans` classes,
   `_JError(0x8F)` if you try to store into `Ans`).
7. Statement separators (`:` and EOL `0x3F`) end a statement; the loop re-enters
   for the next.

The sub-tables `38:5110`/`38:5127` (doc 07) are small token-class lookups
(`38:5110` keys off `tDisp(DE)`/`tOutput(E0)` region; `38:5127` is a paired
classifier) that the dispatch consults; both tail into `RST5` (bjump) handlers.

---

## 7. Confident addresses (space:addr → name)

```
page_38:5987   _ParseInp                  ; parse/eval entry line or formula
page_38:5ab3   parse_eval_expr            ; recursive-descent statement/expr core
page_38:59c5   eval_stmt_entry            ; statement-loop variant (shared LAB_59c8)
page_38:5826   if_else_skip_handler       ; Else-branch skip via block matcher
page_38:6f63   if_stop_stmt_handler       ; per-statement If/Stop dispatch
page_38:4130   blockmatch_end_else        ; nest-counting End/Else scanner
page_38:4180   parse_scan_tokens          ; skip-to-delimiter (2-byte aware)
page_38:4870   goto_lbl_name_scanner      ; scan label name, jump to search
page_38:7600   store_target_name_scanner  ; resolve →VAR store target / Lbl/Goto
page_38:72da   parse_cur_tok
page_38:7248   parse_advance
page_38:5cd8   parse_expect_or_err
page_38:5b7b   parse_init
page_38:758a   _Find_Parse_Formula        ; FindSym + parse stored formula / run prog
page_38:6251   _StoAns
page_38:679f   _RclAns
page_38:74b7   _AnsName                   ; OP1 = Ans name (class 0x72)
page_38:623b   _StoSysTok
page_38:683e   _RclSysTok
page_37:51d3   _Disp                      ; home-screen text display
page_03:4af2   _OutputExpr                ; Output( absolute row,col
page_04:7844   _DispOP1A                  ; format+display OP1 (real)
page_39:4d21   _DispMenuTitle             ; Menu( title bar
page_01:5f4a   _NewLine                   ; cursor newline + scroll
page_01:69b0   _DispDone                  ; finish a Disp
page_01:6518   _RunIndicOn
page_01:6531   _RunIndicOff
page_01:66e5   _GetTokLen                 ; token byte-length (editor)
page_01:66ea   _Get_Tok_Strng             ; token -> display string (editor)
```

I/O command **token-handler** sites (page 02 = the command-exec page; dispatched
from the page-38 evaluator via cross-page jump):
```
page_02:54ef   input_cmd_handler  (tInput DC)
page_02:562f   prompt_cmd_handler (tPrompt DD)
page_02:555d   menu_cmd_handler   (tMenu E6)
page_02:55e7   pause_cmd_handler  (tPause D8)
page_02:673e   output_cmd_handler (tOutput E0)
page_38:6ae6   output_dispatch    (CP E0 in evaluator)
```

---

## 8. Open items
- Reduce the page-02 `Input`/`Prompt`/`Menu` bodies to exact argument-parsing
  order (decompiler output is noisy due to overlapping handlers + cross-page
  jumps; token-compare anchors above are byte-confirmed).
- Confirm the exact `For`/`While`/`Repeat` loop-frame layout on the FPS and how
  `End` re-seeds `parsePtr`.
- Map `getKey`'s keycode table (`37:6700` is a keymap, flagged "bad instruction"
  by the decompiler — it's data, needs manual decode).
