# TI-BASIC execution

TI-BASIC is a token-stream interpreter built around three kinds of state: a
cursor over program bytes, a recursive expression evaluator whose result lives
in `OP1`, and control records that remember where loops and subprograms resume.
This page follows one statement through those layers before describing the
special cases.

The addresses and byte-level decisions below refer to TI-84 Plus OS 2.55MP.
Claims marked [confirmed] are tied to ROM bytes or calculator traces. A
[hypothesis] marks the remaining interpretation of an incompletely decoded
structure.

## The execution pipeline

A stored program is a VAT object of type `ProgObj` (`05h`) or `ProtProgObj`
(`06h`). Its data begins with a little-endian size word followed by exactly that
many token bytes. There are no stored line numbers: `3Fh` separates lines, and
`3Eh` separates colon-delimited statements. [confirmed]

Execution can be read as a pipeline:

```text
VAT program object
    │ size word selects the token body
    ▼
parse cursor (`nextParseByte` .. `basic_end`)
    │ fetch and classify one token
    ▼
statement or recursive expression handler
    │ variable lookup, FP operation, command, or control transfer
    ▼
OP1 result / stored variable / updated parse cursor
```

The page-38 evaluator owns the cursor and grammar. Statement commands can
cross to page 02, control-flow bodies to page 33, display code to pages 01/03/37,
and variable lookup to the VAT routines. Those page changes are continuations
of one interpreter, not separate parsers. [confirmed]

## The token cursor

The cursor is an interval in RAM:

| State | Address | Meaning |
|-------|---------|---------|
| `nextParseByte` | `965Dh` | Current token position |
| `basic_end` | `965Fh` | Inclusive parser bound/refill boundary |
| `basic_start` | `965Bh` | Start of the current body |
| `basic_prog` | `9652h` | Current program/object identity |

The small page-38 helpers are the useful way to reason about cursor movement:

| Routine | Address | Operation |
|---------|---------|-----------|
| `parse_cur_tok` | `38:72DA` | Fetch the current byte and classify `00h`, `3Eh`, and `3Fh` |
| `parse_advance` | `38:7248` | Increment `nextParseByte`, compare it with `basic_end`, and refill when needed |
| `parse_expect_or_err` | `38:5CD8` | Require one token or restore the fault position and raise syntax error |
| `parse_scan_tokens` | `38:4180` | Scan to a statement delimiter without splitting a two-byte token or quoted string |
| `parse_init` | `38:5B7B` | Reset parser-position bytes and parser flags |

Encoded width matters whenever the interpreter skips rather than evaluates.
`_IsA2ByteTok` (`00:1FE8`) searches the 11-byte table at `00:1FF6`; a match
means the lead and following byte must move together. The scanner also treats a
quoted string as one region, so `Then`, `Else`, or `End` bytes inside a string
cannot terminate an outer scan. [confirmed]

```pseudocode
scan_to_delimiter():
  loop:
    token = current_token()
    if token is end, colon, or EOL:
      return
    if token is quote:
      advance through the closing quote or EOL
    else if token is a two-byte lead:
      advance once for the second byte
    advance to the next token
```

This routine does not know the grammar of an expression. Its job is narrower:
preserve token boundaries while another routine searches for a statement or
block delimiter.

## Expressions are nested productions

`_ParseInp` (`38:5987`) initializes parser state for a homescreen expression or
formula and enters the shared evaluator. Stored-program execution arrives with
the program body and parser frame already selected. Both converge on the
recursive expression machinery around `parse_eval_expr` (`38:5AB3`) and the
statement loop at `38:59C5`. [confirmed]

The evaluator is not a flat “token to function” switch. It first maps the
current token to a grammar class, selects a production family, and lets that
handler recursively consume tighter-binding operands. The selector at
`38:7010` chooses among three bases:

| Selector `C` | Handler family | Role |
|--------------|----------------|------|
| Other than `02h` or `03h` | pointer table at `38:4000` | Main grammar productions |
| `02h` | code at `38:478C` | Postfix/power production |
| `03h` | code at `38:7175` | Leaf production |

For the main family, the grammar class in `A` indexes a table of little-endian
handler pointers at `38:4000`. The bytes there are data—beginning `9F 41 F0 45
1C 42 ...`—not executable Z80. The selector doubles the class, reads the
pointer, and calls the chosen production. [confirmed]

```pseudocode
evaluate_production(class, level):
  if level == 2:
    base = 478Ch
  else if level == 3:
    base = 7175h
  else:
    base = word_table_at_4000h

  handler = base[class]       // table family; raw-code families interpret class locally
  return handler(parse_cursor, OP1)
```

This nesting is what gives `^`, multiplication, and addition their precedence.
Binary productions move operands through the OS floating-point stack and apply
operations such as `_FPAdd`, `_FPMult`, or `_BinOPExec`; the completed value is
left in `OP1`. `38:6FB7–6FC2` also folds token classes `F2h` and above by adding
`12h` before dispatch. [confirmed]

The shared statement loop can then do one of three things with the result:

- store it through a parsed variable name;
- write it to `Ans` through `_StoAns` (`38:6251`); or
- pass it to a command or control-flow continuation.

`_AnsName` (`38:74B7`) constructs the internal name with class byte `72h`;
`_RclAns` (`38:679F`) recalls it through the ordinary variable machinery.
[confirmed]

## Statements end locally; blocks scan structurally

A false single-line `If` only has to skip one statement. A false `If ... Then`,
`While`, `Repeat`, or `For(` must find a matching structural boundary without
executing the intervening tokens. That is the purpose of
`blockmatch_end_else` (`38:4130`). [confirmed]

```pseudocode
find_matching_boundary():
  depth = 0
  loop:
    token = current_token()

    if token == Else and depth == 0: return Else
    if token == End  and depth == 0: return End
    if token == End:                    depth -= 1
    if token in {For, While, Repeat}:   depth += 1

    if token == If:
      scan_to_delimiter()
      if current_token() == Then:       depth += 1

    scan_to_delimiter()
```

The distinction between `If condition` and `If condition:Then` is structural:
only the latter opens a block. Nested `Else` tokens are ignored until the depth
returns to zero. The comparisons and counter changes are visible at
`38:4137–417E`; the counter is the 16-bit `DE` register. [confirmed]

### The loop-dispatch boundary remains open

The public page-33 routine behind bcall `grf_435f = 5140h` subtracts `20h`,
accepts 13 indices, and jumps through the table at `33:4381`. Three ABI probes
confirm both bounds outcomes at `33:436D` and `33:4372`. [confirmed]

Natural stored-program traces do not enter `02:5676` or `33:435F`, even when
`FACTOR`, `DFS`, and the paired `For(` benchmark execute loops. The public
page-33 dispatcher is therefore not established as the stored-program loop
transition. Connecting the observed page-38 execution path to the loop-record
operations remains open.

Conceptually, a loop record must retain:

- the loop kind;
- the `For(` variable, limit, and step when applicable; and
- the body cursor used by `End` to resume or exit.

The language behavior requires a saved body position, and the trace shows the
body being revisited. The exact handler transition and byte order of every FPS
loop-record field are still [hypothesis].

The optional closing `)` in `For(` changes marker-to-marker work and parser
buffer state. Neither spelling reaches the page-02 finalization gate in the
paired trace, so the exact causal transition remains open. The measured effect
is covered in [the `For(` parenthesis trap](sub-tibasic-for-paren.md).

### Labels rescan instead of indexing

`goto_lbl_name_scanner` (`38:4870`) reads the label name after `Goto` or `Lbl`.
The search path at `38:7600` rescans the program body for a matching `Lbl`, then
moves `nextParseByte` to it. This explains both the linear cost of `Goto` and
why jumping out of structured loops can bypass normal loop cleanup. The token
and name-scanning path is [confirmed]; the complexity and stack consequence are
standard TI-BASIC behavior.

## Program calls share data but preserve parser control

`prgmNAME` resolves another `ProgObj`, saves the caller's interpreter state,
and evaluates the callee body. It does not create a local variable frame.
Scalars, lists, strings, and `Ans` remain global, so they form the practical
calling convention. [confirmed]

| Event | Effect |
|-------|--------|
| `prgmNAME` | Enter the callee with a nested parser/control frame |
| `Return` | Unwind one BASIC program frame and resume the caller |
| End of body | Return through the same program-frame machinery |
| `Stop` | Terminate the whole BASIC program chain |

The run-confirmed callee transition passes through `38:6910`, calls at
`38:6914`, and enters the body evaluator at `38:778F`. The public parser bcalls
are not substitutes for that prepared state: calling `_ParseInpLastEnt` or
`_Find_Parse_Formula` from an arbitrary `AsmPrgm` reaches parser setup but not a
working BASIC call frame. The negative fixtures end at `ERR:INVALID` and
`ERR:UNDEFINED`, respectively. [confirmed]

For source-level conventions and the `Ans`/scalar/list calling fixture, see
[TI-BASIC programming patterns](sub-tibasic-programming.md#subprogram-interfaces).

## Commands parse arguments, then hand off

Commands use the same expression evaluator for arguments and then cross to a
specialized subsystem. The important boundary is between argument parsing and
the operation itself:

| Command | Parse/dispatch evidence | Downstream operation |
|---------|-------------------------|----------------------|
| `Disp` | page-38 statement handler | `_Disp` at `37:51D3`, then `_NewLine` |
| `Output(` | `38:6AE6`, page-02 handler | `_OutputExpr` at `03:4AF2` |
| `Input` | `02:54EF` | entry editor, `_ParseInp`, variable store |
| `Prompt` | `02:562F` | repeated named-variable entry and store |
| `Menu(` | `02:555D` | `_DispMenuTitle` at `39:4D21`, then label transfer |
| `Pause` | `02:55E7` | display and key-wait loop |
| `getKey` | expression token `ADh` | non-blocking `_GetKey` bcall `4972h` |

`Input` accepts either an optional prompt string or a row/column prefix before
one store target. `Prompt` loops over comma-separated variables and generates
the `NAME=` labels itself. `Menu(` parses a title followed by option-string and
label pairs. These argument-order boundaries are [confirmed]; the entry
editor's internal cursor and redraw state are not yet mapped.

`getKey` is an expression value, not a statement. The table at `37:6700` is a
token-attribute table; returned key codes come from `_GetKey` on page 06. This
distinction prevents a common false inference from the nearby `CP ADh` bytes.
[confirmed]

## What the coverage model establishes

`tools/analyze_tibasic_coverage.py` ties eight finite models to byte signatures
in the pinned ROM. It exhausts 591,360 states across token width, delimiters,
one scan step, one block-depth transition, the extended-class fold, precedence
family selection, command finalization, and page-33 table bounds. Z3 proves a
minimum representative set for the semantic outcomes. [confirmed]

Dynamic evidence is a separate layer. Natural programs reach 34 of 52 outcomes
at 26 selected branch sites. Public-bcall and internal-entry probes bring the
declared outcome set to 52 of 52 while preserving provenance. The report records
only trace hashes and compact counts; raw traces remain outside the repository.
See [TI-BASIC dynamic tracing](sub-tibasic-tracing.md) for commands and exact
boundaries. [confirmed]

This is deliberately not a claim of complete interpreter coverage. The finite
models bound local decisions, while arbitrary token streams, recursion depth,
quoted-string contents, errors, computed handler bodies, VAT state, and
floating-point state remain open.

## Address map

| Address | Role |
|---------|------|
| `00:1FE8` | `_IsA2ByteTok` |
| `38:4000` | Grammar-handler pointer table |
| `38:4130` | Matching `End`/`Else` scanner |
| `38:4180` | Token-aware skip scanner |
| `38:4870` | `Goto`/`Lbl` name scanner |
| `38:5987` | `_ParseInp` |
| `38:5AB3` | Recursive expression evaluator |
| `38:6251` | `_StoAns` |
| `38:6910` | Stored-program statement-body entry |
| `38:6FB7` | Grammar-class validation and high-token fold |
| `38:7010` | Production-family selector |
| `38:7248` | Cursor advance/refill |
| `38:72DA` | Current-token fetch and delimiter classification |
| `38:758A` | `_Find_Parse_Formula` |
| `38:7600` | Store/label name scanning region |
| `38:778F` | Nested stored-program body evaluator |
| `02:5676` | Command finalization gate |
| `33:435F` | Bounded control-flow command dispatcher |

The compact machine-readable evidence is
`tools/tibasic-coverage.json`; the generator verifies the ROM hash and the
local byte signatures before producing a report.
