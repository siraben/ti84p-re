# TI-BASIC programs

*TI-84 Plus OS 2.55MP — feature deep dive.*

How a student-written TI-BASIC program is stored, parsed, and executed on OS
2.55MP. Builds on [07-tokenizer-basic.md](07-tokenizer-basic.md) (tokens, cursor helpers, the page-0x38
evaluator), [05-variables-vat.md](05-variables-vat.md) (OP1 naming, `_FindSym`), and
[11-boot-contexts-errors.md](11-boot-contexts-errors.md) (contexts, `onSP`/`_JError`).

Confidence: [confirmed] = decompiled/byte-verified here, or multiple consistent
signals (token compares, call shape) pin it even where the dense Z80 handler
bodies don't fully reduce in the decompiler; [standard] = documented TI-83+/84+
behavior consistent with what was seen; [hypothesis] = inferred, not yet verified.

---

## 1. How a program is stored [confirmed]

A program is a VAT object of type `ProgObj` (5) / `ProtProgObj` (6) (see [doc 05](05-variables-vat.md)).
Its data is `word size` followed by `size` bytes of tokenized body — the
exact byte stream the parser walks. No line numbers; lines are separated by the
EOL/newline token `0x3F` (`tEnter`, shown as `cVar=='?'` = 0x3F in the
decompiled cursor code). Most tokens are 1 byte; the 11 lead bytes
(`5C 5D 5E 60 61 62 63 7E BB AA EF`, the order of the `ram:1FF6` table) introduce 2-byte tokens ([doc 07](07-tokenizer-basic.md)).

Editing/detokenizing for the program editor uses the page-01 token helpers
([doc 07](07-tokenizer-basic.md), re-confirmed here):
- `_GetTokLen` (`01:66E5`) — returns 1 or 2 for the token at HL (length of the
  token's byte encoding), via `smallfont_glyph_ptr` (`01:6702`).
- `_Get_Tok_Strng` (`01:66EA`) — returns the display string for a token
  (cross-page jump to the name table). The editor calls this per token to paint
  a line; `Disp` of a list/string also routes display text through related
  formatters.

---

## 2. The parse-stream cursor [confirmed]

The interpreter walks the token body through a RAM cursor ([doc 07](07-tokenizer-basic.md), all
re-verified by decompilation):

| Helper | Addr | Behavior |
|--------|------|----------|
| `parse_cur_tok` | `38:72DA` | fetch token at cursor (`parsePtr`); special-cases `:` token `0x3E` (`tColon`)/end `0x00` |
| `parse_advance` | `38:7248` | `parsePtr` (`965D` = `nextParseByte`) ++, bounds-check vs `parseEnd` (`965F` = `basic_end`); refill via `deref_byte` (`38:5B79`) |
| `parse_expect_or_err` | `38:5CD8` | fetch a token; if not the expected one, set `parsePtr` to the fault position and `_ErrSyntax` |
| `parse_scan_tokens` | `38:4180` | skip forward to a delimiter, honoring 2-byte tokens via `_IsA2ByteTok`; used by every block scanner |
| `parse_init` | `38:5B7B` | zero parse position bytes (+6/+7), clear a batch of parser flag bits in the IY flag area |

`parsePtr` is the OS RAM byte `965D` (official equate `nextParseByte`); `parseEnd`
is `965F` (`basic_end`). `parse_scan_tokens`
loop: `parse_cur_tok`; if token==`0x2A` (`tString`, the `"` delimiter it tests for here)
stop, else `_IsA2ByteTok` then `parse_advance` (twice for a 2-byte token). This
is the primitive every control-flow scanner is built on.

---

## 3. Top-level execution model [confirmed]

- `_ParseInp` (`38:5987`) is the entry that parses/evaluates the entry line or a
  formula: it clears RAM `9305` (official equate `EST`, edit-screen height), calls `parse_init`, clears an editing flag
  (`*(IY+0x1F) &= 0xF7`), then tail-calls `_ChkFindSym` to resolve OP1.
  [confirmed]
- `_Find_Parse_Formula` (`38:758A`) `_FindSym`s a named var then parses its
  stored formula; its body switches on var type (`0x0F` Window / `0x10` ZSto /
  `0x11` TblRng special-cased) before the cross-page parse. Used for Y-vars /
  equations and for running a program (resolve ProgObj, point the cursor at
  its body, run the statement loop). [confirmed]
- The statement/expression evaluator is the big recursive-descent core
  `parse_eval_expr` (`38:5AB3`). The interpreter has several entry variants
  that all converge on the same shared inner loop (the code label at `38:59C8`,
  inside `parse_eval_expr`) and the same precedence selector (the label at
  `38:7010`): `38:59C5`, `38:5826`, `38:5CA7`,
  `38:6963`, `38:6F63`. Each variant does statement-type-specific setup/teardown
  (FPS push, flag bits) and then runs the common token loop. [confirmed]

### The shared inner loop (`38:59C8`) [confirmed]

```
loop:
  parse_advance_refill / err_if_not_real_86   ; refresh cursor / housekeeping
  class = chk_tok_end()          ; classify current token
  if (IY+9 & 0x80) class = set_split_rows()  ; alt classify for flagged tokens
  IY+9 &= 0x7F
  if class == 4: parse_pos=fault; _ErrSyntax     ; class 4 = syntax error
  if class <= 3:                 ; an operand/sub-expression
       cls = parse_cur_err_illegal()  ; map token -> grammar class (>0xF1 => +0x12)
       precLevel = 3
  38:7010:                       ; dispatch by precedence level
       if precLevel==2: handler = 0x478c        ; postfix/factorial+power production
       if precLevel==3: handler = 0x7175        ; (nop / leaf)
       else:            handler = 0x4000        ; the base dispatch block
       ... call handler, fold result via FP RSTs into OP1 ...
```

The `param_2`/handler pointer is one of `0x4000` (base/term), `0x478c`
(the postfix `^`/`!` production — it reads `+`/`^` (0x11),
range-checks an exponent as a positive int, `_JError(0x84)` Domain otherwise; it is a
raw code target within `parse_eval_expr`, not a defined function in the live DB),
or `0x7175` (a leaf no-op). Selecting among these by `precLevel` (1/2/3) is how
operator precedence is realized — nesting of productions, not a flat table
(confirms [doc 07](07-tokenizer-basic.md)'s "recursive-descent" claim). Results land in `OP1`; binary
operators are applied via the FP RST shortcuts (RST 30h `_FPAdd`, …) and
`_BinOPExec`.

### Parser dispatch: page 0x38 begins with a handler-pointer table [confirmed]

Raw bytes at `38:4000` are `9F 41 F0 45 1C 42 CC 41 D9 41 …` = a flat array of
2-byte little-endian handler pointers (entries `0x419F, 0x45F0, 0x421C,
0x41CC, 0x41D9, …`), not executable code: `CALL 0x33AB` (`CD AB 33`) appears
nowhere on page 0x38. The `38:7010` precedence
selector indexes this table (`LD HL,0x4000`; add `2×class`; deref), with raw-code
alternates at `0x478C` and `0x7175` for the postfix/leaf classes. Classification
is done by `chk_tok_end` (`38:72E0`) / `parse_cur_err_illegal` (`38:70F8`).

### Results / Ans [confirmed]

- `_StoAns` (`38:6251`) stores OP1 into `Ans` (`_CkOP1Real` path; the bytes that
  follow are the Ans-var token table). `_RclAns` (`38:679F`) = `_AnsName` then
  `_RclVarSym`.
- `_AnsName` (`38:74B7`): `_ZeroOP1; (OP1+1)=0x72` (OP1 holds a name here, so the byte at `0x8479` is the name's type/class tag rather than an exponent) — builds the OP1 name for
  the `Ans` variable (token class `0x72`).
- `_StoSysTok`/`_RclSysTok` (`38:623B`/`683E`) store/recall a system token
  variable (Xmin etc.) into/from OP1.

---

## 4. Control flow [confirmed]

Control-flow tokens (`ti83plus.inc`): `tIf=CE tThen=CF tElse=D0 tWhile=D1
tRepeat=D2 tFor=D3 tEnd=D4 tReturn=D5 tLbl=D6 tGoto=D7 tPause=D8 tStop=D9`.

### Block matcher / End-Else scanner: `blockmatch_end_else` (`38:4130`) [confirmed]

This is the routine that skips a block to its matching `End`/`Else` (used to
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

### If / Then / Else execution [confirmed]

- The `If` statement handler evaluates the condition into OP1 (real). If the
  next token is not `tThen`, it's a single-statement `If` (execute the one
  statement when true, skip it when false). If `tThen`, it's a block.
- The Else path is `if_else_skip_handler` (`38:5826`): on seeing `tElse(D0)` it repeatedly calls
  the block matcher `blockmatch_end_else` (`38:4130`) to skip the Else block to its matching End
  (the "condition was true, ran Then, now jump over Else" case), then rejoins the
  shared loop at `38:59C8`. Other `tElse` compares at `38:57B3/58A6/58C6`
  handle the symmetric "skip Then, run Else" and nested cases.
- `if_isg_stmt_handler` (`38:6F63`) is the per-statement entry that special-cases `tIf` (`0xCE`)
  and `tISG` (`0xDA`, `IS>(`): the second compare is `38:6F6C: CP 0xDA` (`tISG`, the
  adjacent token to `tStop` `0xD9`). For `tIf` it sets grammar class `0x5F` and falls into the
  shared precedence loop to evaluate the condition; unknown leading tokens here
  raise `_JError(0x88)` (`E_Syntax`) for ordinary unknown tokens, or `_JError(0x30)`
  (`E_Version`, "ERR:VERSION") for tokens above `0xF5` (the reserved/newer-token range —
  `0x30` is the message-table index, one below `0x31` ARCHIVE FULL). [confirmed
  bytes]

### For( / While / Repeat / End [confirmed]

- `For(`/`While`/`Repeat` push a loop-control record onto the FPS/loop stack
  recording the loop variable, limit, step, and the `parsePtr` of the loop top
  (so `End` can jump back). `End` pops/updates: increments the `For` variable,
  re-tests the limit, and either re-seeds `parsePtr` to the loop top or falls
  through. The block matcher `blockmatch_end_else` (`38:4130`) is what bounds these bodies during
  skips (e.g. `While 0` skips straight to `End`).
- **Dispatch path (byte-traced).** The For/While/Repeat/End/Return *execution* handlers live
  off page 0x38 — page 0x38 only has the `tFor/tWhile/tRepeat/tEnd` compares inside
  the `blockmatch_end_else` skip scanner (`38:4130…4180`). The live handlers are reached via
  the page-0x02 command dispatcher: `02:54BD` loads a per-token handler pointer
  (`LD HL,0x6A30` for `tFor`=`CP 0xD3`, `0x6A34` for `tEnd`=`CP 0xD4`, `0x6A2A` for
  `tReturn`=`CP 0xD5`), and `tWhile`/`tRepeat` load a loop-type code (`LD A,0x26`/`0x27`)
  and `JP 0x6400`. `02:6400` and the `6A2A/6A30/6A34` stubs set a command index
  (`0x28/0x29/0x2A`) and invoke bcall `0x5140`/`0x513D`, which both resolve to page
  0x33 (`_grf_435f`, target `33:435F`). `33:435F` does `SUB 0x20`, bounds-checks, and
  indexes a 13-entry jump table at `33:4381` (`0x47BB, 0x4A71, 0x4817, 0x4759, 0x47F5,
  0x4AAA, 0x4B36, 0x4B4B, 0x45DE, 0x45D1, 0x459B, 0x4C93, 0x4CE8`) — the actual
  For/While/Repeat/End/Return bodies. The default `For` step uses `_OP2Set1` and the loop
  variable is stored via `_MovFrOP1`; `End` re-seeds the parse cursor from the loop-record's
  saved position. [confirmed dispatch chain into page 0x33; exact FPS record byte layout
  not yet field-mapped — see residual]
- `if_else_skip_handler` (`38:5826`)'s prologue calls `_DeallocFPS1` then
  `restore_982c_ctx` (`38:58DF`, which sets `pTempCnt`/`cleanTmp`) — FPS bookkeeping
  consistent with pushing/popping a loop frame. [hypothesis]
- A trace-backed performance trap exists when `For(` omits its optional closing
  `)` and the first loop-body statement is a single-line false `If`: the
  implicit-close path at `02:5676` interacts with the false-`If` skip path and
  repeatedly advances temporary parser storage. See
  [TI-BASIC `For(` optional paren trap](sub-tibasic-for-paren.md).

### Goto / Lbl: `goto_lbl_name_scanner` (`38:4870`) + scanner at `38:7600` [confirmed]

- `Lbl`/`Goto` use a name scanner. `goto_lbl_name_scanner` (`38:4870`) reads the label name after
  `tGoto(D7)`/`tLbl(D6)`: it advances over the (possibly 2-byte) label token(s)
  until EOL (`'?'`=0x3F) / end, records the position in `parsePtr`, then does a
  `cross_page_jump(0x14)` to the search routine. Token compares for `tLbl(D6)` at
  `38:4870` and `38:7626`; `tGoto(D7)` at `38:762A`. [confirmed]
- `Goto` resolves by rescanning the program body from the top for a matching
  `Lbl name`, then setting `parsePtr` there — the classic TI-BASIC behavior that
  makes `Goto` O(program size) and makes `Goto` out of a loop leak the loop's
  stack frame. [inferred — standard, consistent with the rescan call shape]
- `Return`/`Stop` (`tReturn=D5`/`tStop=D9`) terminate execution at different
  scopes: `Return` exits the current BASIC program and resumes the caller, while
  `Stop` exits the whole BASIC program chain back to the homescreen context.
  `CALLSUB`/`SUBRT` and `CALLSTOP`/`STOPSUB` are run-confirmed fixtures for
  those two cases. [confirmed]

---

## 5. I/O commands

The display primitives live on pages 01/04/37; the command (token)
handlers that parse arguments live mostly on page 0x02 (the TI-BASIC
command-execution page) and page 0x39, reached from the page-38 evaluator via
cross-page jump (`RST2`/bjump). Token-compare sites located by ROM scan:

| Command | Token | Handler site(s) | Display primitive used |
|---------|-------|-----------------|------------------------|
| `Disp` | `tDisp=DE` | dispatch → `_Disp` (`37:51D3`), bcall site `38:45A4` | `_Disp`, `_NewLine`, `_DispDone` |
| `Output(` | `tOutput=E0` | `38:6AE6` (CP E0), `02:673E`, `01:7D3D` | `_OutputExpr` (`03:4AF2`) at row,col |
| `Input` | `tInput=DC` | `02:54EF`, `02:56AB`, `02:5917`, `01:7DEF` | prompt + entry-line editor + `_ParseInp` of typed text |
| `Prompt` | `tPrompt=DD` | `02:562F`, `02:5786`, `02:590E`, `00:4C5C` | like `Input` but auto-labels `NAME=?` |
| `Menu(` | `tMenu=E6` | `38:5A8A` (CP E6), `02:555D`, `06:4A17` | `_DispMenuTitle` (`39:4D21`) + branch on choice |
| `Pause` | `tPause=D8` | `02:55E7`, `02:6684`, `39:6B8E`, `3A:7E7C` | display then wait for `[ENTER]` via key loop |
| `getKey` | `tGetKey=AD` | `37:6700` (a token-attribute table, not a keymap), `3A:7E8A` | non-blocking `_GetKey` (bcall `0x4972`, page 06); returns keycode→OP1 |
| `ClrHome` | (cmd token) | clears text shadow + home cursor | `_ClrLCDFull` / home-cursor reset |

Details:

- `Disp` / `Disp expr` — `_Disp` (`37:51D3`): sets a "text in display" flag
  (`IY+0x0D |= 4`), and when the active context is the home/run context
  (`cxCurApp == 'D'`) it clears graph-style state and cross-page-jumps into the
  paint routine; otherwise `RST5` (bjump) to the generic display path. Numeric
  results format via `_DispOP1A` (`04:7844`) → `_CkOP1Real`; strings/lists route
  through their formatters. Each `Disp` item ends with `_NewLine` (`01:5F4A`):
  `curCol=0`, and if `curRow+1 >= winBtm` it triggers scroll, else `curRow++`.
  `_DispDone` (`01:69B0`) finishes. [confirmed for `_Disp`/`_NewLine`]
- `Output(row,col,value` — `_OutputExpr` (`03:4AF2`, cross-page) writes at an
  absolute (row,col) without scrolling. Handler parses three comma-separated
  args, range-checks row/col, then calls it. [confirmed]
- `Input` / `Prompt` — these handlers (page 02) drop into the entry-line
  editor: show the prompt (`?` for `Input`, `VAR=` for `Prompt`), let the user
  type, tokenize the input, and feed it back through the parser (`_ParseInp`) to
  store into the target variable. The exact argument-parsing order (byte-traced):

  - `Input` dispatch is `02:54EF` (`CP 0xDC`) and the body entry `02:54F6` reached via
    `02:641F` (`CP 0xDC → POP AF; CALL 0x649E; EX DE,HL; JP 0x54F6`). Order: (1) check
    for an optional leading argument — a string/`Str`/`"…"` prompt *or* a `(row,col)`
    pair, comma-terminated; (2) parse the single store target variable; (3) print the
    prompt (`?` if no custom prompt was given); (4) run the entry-line editor; (5) tokenize +
    `_ParseInp` the typed text; (6) `_MovFrOP1`/store into the target. With no args at
    all, `Input` pauses on the graph screen with a free-moving cursor.
  - `Prompt` dispatch is `02:562F` (`CP 0xDD`) → `02:6699`. It is a loop over a
    comma-separated variable list (`02:6699 LD DE,1; … ; 02:66BF CALL 0x1942; CP 0x04;
    JR NZ,error` — each list item must classify as a storable real/var, type 4). For
    each variable: resolve its name (`02:66AC CALL 0x1DF3` then cross-page `CALL 0x3A89`),
    auto-print "`NAME=`", run the editor, parse the typed value, store it, then advance to
    the next comma item. [confirmed token sites + loop/validation bytes; entry-line
    editor internals dense]
- `Menu(` — dispatched on page 02 at `02:555D` (`CP 0xE6`, → handler pointer
  `LD HL,0x6A16; JP 0x5676`). Argument order: (1) parse the title string argument;
  (2) then parse (option-string, Lbl-name) pairs, up to 7. `_DispMenuTitle` (`39:4D21`)
  draws the title; the handler stores each branch-target `Lbl`, draws the option rows,
  blocks for a key, and on selection performs a `Goto`-style jump to the chosen `Lbl`.
  Token site also `38:5A8A`. [confirmed]
- `Pause` — displays (optionally an expression), then spins in a key-read
  loop until `[ENTER]`; `Pause expr,N` (2.55MP) scrolls a list/matrix. Sites at
  `02:55E7`, `39:6B8E`. [confirmed]
- `getKey` — non-blocking: reads the current key and returns its code in OP1
  (0 if none). Used as a value inside expressions, so it's wired as an operand
  token (`tGetKey=AD`) in the evaluator, not a statement. The keycode read itself is
  the OS system call `_GetKey` (bcall `0x4972` → page 06 `06:491E`); the per-key
  numeric codes returned are the standard TI `kXxx` constants (e.g. `kRight=1`,
  `kLeft=2`, `kUp=3`, `kDown=4`, `kEnter=5`, `kClear=9`, `k0..k9 = 0x8E…`).
  `37:6700` is a fixed-width token-attribute / opcode-template table keyed by token, which
  Ghidra renders as code. Byte-decoding it (`FE AD 1C 1B 18 EC 31 00
  84 …`) shows it begins `CP 0xAD` (tGetKey) / `CP 0x55` / `CP 0x54` and continues as
  records keyed by token (`FE xx` 1-byte, `FB xx`/`FC xx`/`F4 89` 2-byte tokens — getKey,
  stat/distribution and finance tokens), used by a (de)tokenizer/compiler rather than as a
  key→code map. The keycodes a `getKey` returns come from `_GetKey` on page 06, not this table.
  [confirmed: 37:6700 is a token-descriptor table; keycodes come from
  `_GetKey` on page 06]
- `ClrHome` — clears the home-screen text shadow and resets the cursor to
  (0,0). [inferred — standard]

The `_RunIndicOn`/`Off` (`01:6518`/`6531`) busy indicator runs during
execution: `_RunIndicOn` sets `indicBusy=0xF0`, `indicCounter=1`, enables
interrupts, sets `IY+0x12 |= 1`. The interpreter turns it on while a program
runs and off at `Done`. [confirmed]

---

## 6. Token dispatch & precedence — summary [confirmed]

1. `parse_cur_tok` fetches a token at `parsePtr`.
2. `chk_tok_end` (`38:72E0`) classifies it into a small class number (`<=3` operand/expr,
   `4` = syntax error, others = operator/command). Flagged tokens reclassify via
   `set_split_rows` (`ram:20A0`) when `IY+9 & 0x80`.
3. `parse_cur_err_illegal` (`38:70F8`) validates the current token; its caller (at `38:6FBE`) then
   maps the token byte to a grammar/precedence class — tokens `≥0xF2` get `+0x12` (`38:6FBE: ADD A,0x12`),
   folding the high token page into the class space.
4. The precedence level (`cVar4` = 1/2/3) selects the production handler base:
   `0x4000` (base term — the flat handler-pointer table, indexed by token class),
   `0x478C` (postfix `^`/`!`), or `0x7175` (leaf) — `0x478C` and `0x7175` are raw code
   targets inside `parse_eval_expr` (not defined functions in the live DB), whereas
   `0x4000` is the pointer table itself. Nesting these realizes precedence.
5. Binary ops fold operands via FP RSTs (RST 30h `_FPAdd`; `_FPMult`=`00:238B`, …)
   / `_BinOPExec`, leaving the result in `OP1`.
6. Variable tokens become an OP1 name (type byte + name) and resolve via
   `_FindSym`/`_RclVarSym` ([doc 05](05-variables-vat.md)); store targets (`→VAR`) resolve through the
   `38:7600` name scanner (handles `[A]`/`L1`/`Str1`/Y-var/`Ans` classes,
   `_JError(0x8F)` on an attempt to store into `Ans`).
7. Statement separators (`:` and EOL `0x3F`) end a statement; the loop re-enters
   for the next.

The sub-tables `38:5110`/`38:5127` ([doc 07](07-tokenizer-basic.md)) are small token-class lookups
(`38:5110` keys off `tDisp(DE)`/`tOutput(E0)` region; `38:5127` is a paired
classifier) that the dispatch consults; both tail into `RST5` (bjump) handlers.

---

## 7. Confident addresses (space:addr → name)

```
page_38:5987   _ParseInp                  ; parse/eval entry line or formula
page_38:5ab3   parse_eval_expr            ; recursive-descent statement/expr core
page_38:59c5   eval_stmt_entry            ; statement-loop variant (shared loop label 38:59C8)
page_38:5826   if_else_skip_handler       ; Else-branch skip via block matcher
page_38:6f63   if_isg_stmt_handler        ; per-statement If/IS>( dispatch
page_38:4130   blockmatch_end_else        ; nest-counting End/Else scanner
page_38:4180   parse_scan_tokens          ; skip-to-delimiter (2-byte aware)
page_38:4870   goto_lbl_name_scanner      ; scan label name, jump to search
page_38:7600   store_target_name_scanner  ; →VAR store-target name scanner (inferred; live DB auto-name is set_tblgraph_draw_xpage)
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

I/O command token-handler sites (page 02 = the command-exec page; dispatched
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

## 8. Dynamic confirmation and traceable examples

The current headless trace workflow confirms the parser/evaluator path with both
homescreen input and stored programs. A full-range TilEm trace of `2+3` on the
homescreen reaches page-38 parser functions including `eval_stmt_entry`
(`38:59C5`), `parse_eval_expr` (`38:5AB3`), `parse_init` (`38:5B7B`),
`parse_advance` (`38:7248`), `chk_tok_end` (`38:72E0`), and `_StoAns`
(`38:6251`).

The stored-program samples in `tools/tibasic-samples/` are generated with
`tools/tibasic_samples.py --write-dir tools/tibasic-samples`. Each sample has
readable `.bas`, hex-text `.tok`, and loadable `.8xp` forms. The `.8xp`
validation traces below were run on 2026-06-06/07 against OS 2.55MP in
`tools/rom.bin` with a local headless TilEm patch that loads command-line `.8xp`
files before running the macro; the traces therefore include startup
link-transfer code as well as interpreter execution.

### Hello world

```ti-basic
ClrHome
Disp "HELLO, WORLD"
```

Body bytes:

```text
E1 3F DE 2A 48 45 4C 4C 4F 2B 29 57 4F 52 4C 44 2A 3F
```

Observed run: `HELLO.8xp` displays `HELLO, WORLD` and then `Done`. The trace hits
`eval_stmt_entry`, `parse_refill`, `parse_advance`, and `_Disp` (`37:51D3`).

### Factorial loop

```ti-basic
Prompt N
1->F
For(I,1,N)
F*I->F
End
Disp F
```

Body bytes:

```text
DD 4E 3F 31 04 46 3F D3 49 2B 31 2B 4E 11 3F 46 82 49 04 46 3F D4 3F DE 46 3F
```

Observed run: `FACTOR.8xp` with prompt input `5` displays `N=5`, result `120`,
and then `Done`. The trace hits `eval_stmt_entry`, page-38 parser/refill paths,
`_FPMult` (`ram:238B`), and `_Disp` (`37:51D3`).

### List/data manipulation

```ti-basic
{3,1,4,1,5}->L1
SortA(L1)
cumSum(L1)->L2
sum(L1)->S
Disp L1
Disp L2
Disp S
```

Body bytes:

```text
08 33 2B 31 2B 34 2B 31 2B 35 09 04 5D 00 3F E3 5D 00 11 3F BB 29 5D 00 11 04 5D 01 3F B6 5D 00 11 04 53 3F DE 5D 00 3F DE 5D 01 3F DE 53 3F
```

Observed run: `DATA.8xp` displays sorted `L1` as `{1 1 3 4 5}`, cumulative `L2`
as `{1 2 5 9 14}`, sum `14`, and then `Done`. The trace hits 2-byte/list paths
including `resolve_2byte_var2`, `chk_list_type`, `store_list_elem*`,
`list_var_index`, and `list_fold_dispatch` (`02:6104`).

### `Asm(` smoke test

Safe `Asm(` tracing uses a program that returns immediately:

```ti-basic
AsmPrgm
C9
```

`C9` is Z80 `RET`. A BASIC wrapper can show that control returns to TI-BASIC:

```ti-basic
Disp "BEFORE"
Asm(prgmASMRET)
Disp "AFTER"
```

Raw bodies:

```text
ASMRET:  BB 6C 3F 43 39 3F
ASMCALL: DE 2A 42 45 46 4F 52 45 2A 3F BB 6A 5F 41 53 4D 52 45 54 11 3F DE 2A 41 46 54 45 52 2A 3F
```

`Asm(` is the 2-byte token `BB 6A`; `AsmPrgm` is `BB 6C`; the displayed `prgm`
prefix in `Asm(prgmASMRET)` is the program-name token `0x5F`, followed by the
name characters and the closing `)` token. Observed run: loading `ASMCALL.8xp`
and `ASMRET.8xp` displays `BEFORE`, executes `Asm(prgmASMRET)`, displays
`AFTER`, and then `Done`. The trace shows the `Asm(` handler parse the
`prgmASMRET` token stream, bcall `_ExecutePrgm` (`4E7C`, target `07:5758`),
compile/copy the `AsmPrgm` body, hand off through `07:57B4`, and execute the
payload byte itself at `ram:9D95 op=0x000000C9`, returning to BASIC immediately
after. This `_ExecutePrgm` route is the ASM executor; it is not the ordinary
BASIC `prgmNAME` subprogram path.

`ASMBRIDG.8xp` demonstrates a cooperative ASM-directed BASIC callback that
routes through a BASIC variable. The wrapper runs:

```ti-basic
Disp "BEFORE"
Asm(prgmASMSIG)
If Ans
prgmZZBASIC
Disp "AFTER"
```

with `ASMSIG.8xp`:

```ti-basic
AsmPrgm
EF9B41EFBF4AC9
```

and target:

```ti-basic
Disp "CALLED"
```

The payload bytes are `rst 28h; .dw 419B` (`_OP1Set1`), `rst 28h; .dw 4ABF`
(`_StoAns`), `ret`. Observed run: loading `ASMBRIDG.8xp`, `ASMSIG.8xp`, and
`ZZBASIC.8xp` displays `BEFORE`, `CALLED`, `AFTER`, then `Done`. The trace
hits the `AsmPrgm` payload at `ram:9D95`, `_OP1Set1` (`00:1B38`), `_StoAns`
(`38:6251`), `_AnsName` (`38:74B7`) during `If Ans`, and the ordinary
`prgmZZBASIC` body evaluator path (`38:6910` -> `38:6914` -> `38:778F`).
This is the practical callback convention: ASM returns a value through a BASIC
variable, and BASIC performs the actual program call.

`ASMRTN.8xp` demonstrates the same `Ans` convention as a numeric return value:

```ti-basic
Asm(prgmASMVAL)
Ans+3->A
Disp A
```

with `ASMVAL.8xp`:

```ti-basic
AsmPrgm
EFA741EFBF4AC9
```

The payload bytes are `rst 28h; .dw 41A7` (`_OP1Set2`), `rst 28h; .dw 4ABF`
(`_StoAns`), `ret`. Observed run: loading `ASMRTN.8xp` and `ASMVAL.8xp`
displays `5`, then `Done`. The trace hits `ram:9D95`, `_OP1Set2` (`00:1B50`),
`_StoAns` (`38:6251`), `_AnsName` while evaluating `Ans+3`, `_FPAdd`, and
`_Disp`. This confirms that `Ans` is a practical scalar return channel from an
`AsmPrgm` back into BASIC.

### Animation, graphing, and BASIC subprogram calls

Additional generated fixtures extend coverage beyond arithmetic/list samples:

```ti-basic
ClrHome
For(I,1,8)
Output(1,I,"X")
End
Disp "DONE"
```

Observed run: `ANIMTXT.8xp` displays a row of `X` characters, `DONE`, and then
`Done`. The trace hits `_OutputExpr` (`03:4AF2`), page-38 parser/loop paths,
`_Disp`, and LCD text routines.

```ti-basic
ClrDraw
0->Xmin
94->Xmax
0->Ymin
62->Ymax
Line(0,0,94,62)
Line(0,31,94,31)
Line(47,0,47,62)
Circle(47,31,10)
Text(0,0,"DFS")
DispGraph
```

Observed run: `GRAPHV.8xp` ends on the graph screen with `DFS`, axes, a circle,
and a diagonal line visible. The trace hits `_GrBufClr`, `_StoSysTok`, `_ILine`
(`04:4029`), `graph_pixel_op`, `_IPoint`, and `_PDspGrph` (`04:7904`).

```ti-basic
ClrDraw
0->Xmin
94->Xmax
0->Ymin
62->Ymax
Line(10,44,35,54)
Line(10,44,35,14)
Line(35,54,55,29)
Circle(10,44,3)
Circle(35,54,3)
Circle(35,14,3)
Circle(55,29,3)
Text(16,8,"1")
Text(6,33,"2")
Text(46,33,"3")
Text(31,53,"4")
DispGraph
```

Observed run: `GRAPHDFS.8xp` draws the DFS sample's four-node topology on the
graph screen: nodes `1`, `2`, `3`, and `4` with edges `1-2`, `1-3`, and `2-4`.
The trace hits `_ILine` (`04:4029`), `graph_pixel_op`, `_IPoint`, small-font
glyph rendering, `_PDspGrph` (`04:7904`), `_StoSysTok` window stores,
`_RestoreDisp`, and page-38 statement evaluation.

`GRAPHLST.8xp` draws the same topology from list data. It stores edge endpoint
coordinates in `L1`–`L4`, stores node centers in `L5` and `L6`, then loops over
those lists:

```ti-basic
For(I,1,3)
Line(L1(I),L2(I),L3(I),L4(I))
End
For(I,1,4)
Circle(L5(I),L6(I),3)
End
```

Observed run: the final frame matches the `GRAPHDFS` topology and passes the
same node/edge crop-region checks. The trace hits `list_var_index`,
`_GetLToOP1`, `_ILine`, `_IPoint`, `_PDspGrph`, and `_StoSysTok`, confirming a
list-driven graph visualization path rather than only hard-coded draw
coordinates.

```ti-basic
0->A
prgmSUBRT
Disp A
```

with callee:

```ti-basic
Disp "SUB"
A+1->A
Return
```

Observed run: loading `CALLSUB.8xp` and `SUBRT.8xp` displays `SUB`, then `1`,
then `Done`. This confirms the practical BASIC calling convention: caller and
callee share variables, and `Return` resumes the caller. The trace hits VAT/name
lookup, parser entry/refill paths, the program-body evaluator call at `38:6914`
into `eval_eqn_recursive` (`38:778F`), shared `A` store/recall, and `_Disp`.

`ABICALL.8xp` and `ABISUB.8xp` exercise more of that convention:

```ti-basic
{2,4,6}->L1
7
prgmABISUB
Disp A
Disp L1
Disp Ans
```

with callee:

```ti-basic
Ans+L1(2)->A
9->L1(3)
A
Return
```

Observed run: the caller displays `11`, `{2 4 9}`, `11`, then `Done`. The callee
reads the caller's `Ans` and `L1`, writes shared scalar `A`, mutates shared
`L1`, leaves `Ans` as `11` by evaluating `A`, and returns. The trace hits the
BASIC subprogram body path plus `_AnsName` and list store paths, so this is a
confirmed scalar/list/`Ans` ABI fixture.

`CALLSTOP.8xp` and `STOPSUB.8xp` cover the non-returning subprogram case:

```ti-basic
Disp "BEFORE"
prgmSTOPSUB
Disp "AFTER"
```

with callee:

```ti-basic
Disp "STOP"
Stop
```

Observed run: the caller displays `BEFORE`, the callee displays `STOP`, and the
homescreen displays `Done`; caller text `AFTER` does not appear. The smoke
runner checks the `BEFORE`, `STOP`, and `Done` regions, plus a bounded low-pixel
region where `AFTER` would appear if execution resumed. The trace reaches the
BASIC subprogram body path and `_Disp`, so this confirms that `Stop` terminates
the whole BASIC program chain instead of returning to the caller.

The ordinary BASIC subprogram path is separate from `Asm(`. In the validated
trace it does not hit `_ParsePrgmName`, `_ExecutePrgm`, `_Find_Parse_Formula`,
or `_SetParseVarProg`; it uses the page-38 parser/VAT/body evaluator path and
then either resumes the caller through BASIC's own `Return` handling or exits
the caller chain through `Stop`.

`ASMFIND.8xp` and `ZZFIND.8xp` prove the narrower ASM-side lookup case. The
payload builds `OP1={ProgObj,"ZZBASIC"}` and bcalls `_ChkFindSym`; the trace
hits `ram:9D95` and `findsym_scan`, then the BASIC wrapper displays `AFTER` and
`Done`. `ZZBASIC`'s `CALLED` line does not display, so lookup is confirmed but
execution is not.

`ASMPARSE.8xp` and `ZZPARSE.8xp` turn that boundary into a negative fixture.
The payload uses the same `OP1={ProgObj,"ZZBASIC"}` setup as `ZZFIND`, but
bcalls `_ParseInpLastEnt` instead. The trace reaches `_ParseInpLastEnt`,
`_ParseInp`, `parseinp_find_setup`, `findsym_scan`, `parse_init`, and
`eval_stmt_entry`; the final screen is `ERR:INVALID` / `1:Quit` / `2:Goto`, and
`ZZBASIC`'s `CALLED` line does not display.

`ASMFORM.8xp` and `ZZFORM.8xp` turn the `_Find_Parse_Formula` boundary into the
same kind of generated negative fixture. The payload again builds
`OP1={ProgObj,"ZZBASIC"}`, but bcalls `_Find_Parse_Formula` (`4AF2`, target
`38:758A`). The trace reaches `ram:9D95`, `_Find_Parse_Formula`,
`parse_init_findsym`, `findsym_scan`, and `eval_stmt_entry`; the final screen is
`ERR:UNDEFINED` / `1:Quit` / `2:Goto`, and `ZZBASIC`'s `CALLED` line does not
display.

The full `CALLSUB` smoke trace does hit `_ParseInpLastEnt`/`_ParseInp` once,
because the macro starts the program by submitting `prgmCALLSUB` from the
homescreen. That launch parse resolves the top-level program and seeds the
private parser RAM. It does not make `_ParseInpLastEnt` a reusable
ASM-to-BASIC ABI: `ASMPARSE` shows that calling `_ParseInpLastEnt` with only
`OP1={ProgObj,"ZZBASIC"}` reaches `ERR:INVALID` instead of the target program.

The relevant page-38 evaluator transition is private state, not a bcall ABI:
`stmt_eval_body_entry` (`38:6910`) calls the token scanner, then
`call_eval_eqn_recursive` (`38:6914`) directly calls `eval_eqn_recursive`
(`38:778F`). At the first observed hit in the `CALLSUB` trace, the parser
cursor/end, OPS/temp-stack pointers, OP1, stack depth, and IY parser flags are
already live. This is why `ASMFIND` can successfully `_ChkFindSym` a BASIC
program name, but `ASMFORM` still reaches `ERR:UNDEFINED` instead of running
that program through `_Find_Parse_Formula`.

The `_ParseInpLastEnt` fixture narrows the parser-entry boundary further:
`_ParseInp` variants are not byte-stream program-call ABIs; they expect
parser/FPS stack state that a live BASIC caller has already established.

The forced-command/edit-buffer path is another boundary, not an ABI. A temporary
`AsmPrgm` that calls `_JForceCmd(kEnter)` reaches `_JForceCmd` (`00:0747`) but
does not return to the BASIC wrapper; the final screen repeats the wrapper's
first line and `Done` instead of reaching the wrapper's following statement.
The reason is visible in page-0 disassembly: `_JForceCmd` reloads `SP` from the
OS command-loop state at `85BC`. A second payload that calls `_PutTokString`
(`06:46FD`) for the bytes of `prgmZZBASIC` returns to BASIC, but only
renders/inserts token text; combining `_PutTokString` with `_JForceCmd` still
never displays the target program's `CALLED` line. `_rclToQueue` (`06:5F29`) is
an edit-buffer queue helper guarded by `rclFlag.enableQueue`, not a standalone
program executor.

`_ExecuteNewPrgm` (`00:265F`) is also stateful. An `AsmPrgm` probe with
`OP1=ProgObj` and `HL -> "ZZBASIC",0` enters `_ExecuteNewPrgm` and
`findsym_scan`, then reaches `ERR:SYNTAX`. The same probe with `ZZBASIC` loaded
as `ProtProgObj` and `OP1=06` gets through the copy/jump tail at `00:268A` and
`00:268F`, but still stops at `ERR:SYNTAX` without displaying the target
program's `CALLED` line.

```ti-basic
{5,4,3,2,1}->L1
{5,6,7,8,9}->L2
{0,0,0,0,0,0}->L3
0->C
For(I,1,5)
L1(I)+L2(I)+C->S
int(S/10)->C
S-10*C->L3(I)
End
C->L3(6)
Disp L3
Disp L3(6)
```

Observed run: `BIGADD.8xp` displays the low-end digits of `L3` as
`{0 1 1 1 1 ...}`, then an explicit carry line `1`, then `Done`, representing
`12345 + 98765 = 111110` in little-endian decimal digits. The trace hits
`list_var_index`, `_AdrLEle`, `_GetLToOP1`, `_PutToL`, `store_list_elem*`,
`fnint_body`, `_FPDiv`, `_FPAdd`, `_FPSub`, and `_FPMult`.

```ti-basic
{3,2,1}->L1
{5,4}->L2
{0,0,0,0,0}->L3
For(I,1,3)
For(J,1,2)
L3(I+J-1)+L1(I)*L2(J)->S
int(S/10)->C
S-10*C->L3(I+J-1)
L3(I+J)+C->L3(I+J)
End
End
Disp L3
Disp L3(4)
```

Observed run: `BIGMUL.8xp` displays `{5 3 5 5 0}`, then `5`, then `Done`,
representing `123 * 45 = 5535` in little-endian decimal digits. The trace hits
nested `For(` loop parsing, list element reads/stores, `_FPMult`, `_FPAdd`,
`_FPSub`, `_GetLToOP1`, and `_PutToL`.

```ti-basic
{1,1,2}->L1
{2,3,4}->L2
{0,0,0,0}->L3
{1,0,0,0}->L4
1->P
While P
L4(P)->V
P-1->P
If L3(V)=0
Then
1->L3(V)
Disp V
For(E,1,3)
If L1(E)=V
Then
P+1->P
L2(E)->L4(P)
End
End
End
End
Disp L3
```

Observed run: `DFS.8xp` displays traversal `1`, `3`, `2`, `4`, then visited
flags `{1 1 1 1}`, then `Done`. The trace hits nested control-flow scanners
(`blockmatch_end_else`, `parse_scan_tokens`), `eval_stmt_entry`, parser
refill/advance, and list stack read/write paths (`list_var_index`, `_AdrLEle`,
`_GetLToOP1`, `_PutToL`, `store_list_elem*`).

See [TI-BASIC programming patterns](sub-tibasic-programming.md) for performance
rules and larger source-level examples.

---

## 9. Resolved / residual

Three argument-handling and dispatch details, grounded in the bytes (see §5 / §4):

- `Input`/`Prompt`/`Menu` argument order (§5). `Input` (`02:54EF`→`54F6`):
  optional leading prompt-string *or* `(row,col)` → single store var → editor → parse →
  store. `Prompt` (`02:562F`→`6699`): loop over comma-separated type-4 storable vars,
  each "`NAME=`" → editor → parse → store. `Menu(` (`02:555D`): title string, then up to 7
  (option-string, `Lbl`) pairs, then key-select → `Goto`-style jump.
- `For`/`While`/`Repeat`/`End` dispatch (§4). Execution handlers live on
  page 0x33 (jump table `33:4381`, entered via bcall `0x5140`/`0x513D` = `33:435F` from
  the page-0x02 dispatcher at `02:54BD`/`02:6400`), not page 0x38. `End` re-seeds the parse
  cursor from the loop record's saved top position.
- `getKey` `37:6700` (§5). A fixed-width
  token-attribute / opcode-template table keyed by token (`FE/FB/FC/F4`-prefixed). The
  keycodes a `getKey` returns come from the OS `_GetKey` system call (bcall `0x4972`, page 06),
  which returns the standard `kXxx` constants.

Residual (genuinely unverified — would need deeper page-0x33 paged tracing):
- The exact byte layout of the For/While/Repeat loop-control record on the FPS (field
  order/sizes for loop var, limit, step, and saved `parsePtr`) is not yet field-mapped; only
  the dispatch chain into the `33:4381` handlers is confirmed.
- The page-0x02 `Input`/`Prompt` entry-line editor internals (cursor/redraw, 2.55MP
  multi-line) remain dense and are only confirmed at the argument-parse boundary.
