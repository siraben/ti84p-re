# TI-BASIC `For(` paren trap

This note explains a TI-BASIC performance trap:

```ti-basic
For(I,1,N
If 0
1
End
```

is much slower than the visually similar:

```ti-basic
For(I,1,N)
If 0
1
End
```

The closing `)` is syntactically optional, but it is not performance-neutral
when the first loop-body statement is a single-line false `If`.

Confidence: [confirmed] = measured in TilEm instruction traces or read from
ROM bytes; [standard] = consistent with the interpreter structure but not
field-mapped down to every loop-frame byte.

---

## Benchmark shape

The test program brackets only the loop with an `AsmPrgm` marker:

```ti-basic
Asm(prgmZMARK)
For(I,1,100)
If 0
1
End
Asm(prgmZMARK)
Disp I
```

`ZMARK` is:

```ti-basic
AsmPrgm
C9
```

`C9` is Z80 `RET`. In both traces the marker payload executes at
`ram:9D95 op=0xC9`, so the interval from the first marker `RET` to the second
marker `RET` excludes boot, link transfer, menu navigation, and the final
display.

The compared token streams differ by exactly one byte in the `For(` header:

```text
For(I,1,25) / If 0:  D3 49 2B 31 2B 32 35 11 3F CE 30 ...
For(I,1,25  / If 0:  D3 49 2B 31 2B 32 35    3F CE 30 ...
```

`D3` is `tFor`, `11` is `tRParen`, `3F` is EOL, and `CE` is `tIf`.

## Trace results

All runs completed and displayed the expected final loop variable (`26` for
`N=25`, `101` for `N=100`). Counts are marker-to-marker instruction records and
Z80 clock deltas from the TilEm trace.

| Loop body | N | `For(... )` | `For(...` | Delta |
|-----------|---|-------------|-----------|-------|
| `If 0` / `1` | 25 | 144,805 instr / 1,519,710 clocks | 156,292 instr / 1,604,282 clocks | +7.9% instr / +5.6% clocks |
| `If 0` / `1` | 100 | 521,723 instr / 5,498,347 clocks | 885,912 instr / 8,862,729 clocks | +69.8% instr / +61.2% clocks |
| `If 1` / `1` | 25 | 185,032 instr / 1,920,085 clocks | 179,874 instr / 1,859,796 clocks | -2.8% instr / -3.1% clocks |

The true-condition control matters: omitting `)` is not inherently slower. The
large slowdown appears when the omitted close is followed immediately by a
single-line false `If`.

## Dispatch difference

The optional close is handled by the page-2 command-finalization gate
`02:5676` [confirmed]:

```z80
02:5676  LD A,C
02:5677  CP 11h          ; explicit ")"
02:5679  JR Z,56C3h
02:5683  OR A            ; implicit close / statement end
02:5684  JP NZ,2708h     ; syntax/type error for other cases
02:5687  CALL 5675h      ; direct command handler path
```

The explicit `)` path (`02:56C3...`) calls through the command cleanup path
before returning to statement execution. The implicit-close path (`C=0`) calls
the command handler directly. For `For(`, that handler is the page-2 stub
`02:6A30`, which calls bcall `_grf_435f` (`33:435F`) and indexes the control-flow
jump table at `33:4381`; the `For` entry is table index `0x29 - 0x20 = 9`, and
`End` is index `0x2A - 0x20 = 10` [confirmed].

That one-byte syntax difference therefore changes the parser state at exactly
the point where the `For` loop frame records the body cursor.

## What the slow case does

The marker interval profiler shows that the no-paren/false-`If` case spends its
extra time in name/VAT scanning and pointer walking, not arithmetic:

```text
false N=25, no paren minus explicit paren:
  +18,900 instr  07:565F  findsym_scan
   +3,600 instr  ram:1787      dec_hl_tail_1787
   +1,800 instr  ram:1785      dec_hl_tail_1785
     +900 instr  ram:1784      dec_hl_tail_1784
```

The parser-cursor writes explain why. In the explicit-paren trace, the
single-line false `If` path repeatedly uses the same temporary parser buffer:

```text
... write nextParseByte=9EA8, parseEnd=9EA8
... restore nextParseByte=9E3B, parseEnd=9E4C
... write nextParseByte=9EA8, parseEnd=9EA8
... restore nextParseByte=9E3B, parseEnd=9E4C
```

In the omitted-paren trace, the equivalent temporary buffer advances on each
iteration:

```text
iteration 1: nextParseByte=9EA7, parseEnd=9EA7
iteration 2: nextParseByte=9EB4, parseEnd=9EB4
iteration 3: nextParseByte=9EC1, parseEnd=9EC1
iteration 4: nextParseByte=9ECE, parseEnd=9ECE
iteration 5: nextParseByte=9EDB, parseEnd=9EDB
```

Those addresses come from writes to `nextParseByte` (`0x965D`) and `basic_end`
(`0x965F`) inside the marker interval. The advancing high-water mark matches
the growing `findsym_scan` cost: the interpreter keeps allocating/walking
temporary expression storage instead of reusing one stable temporary range.

## Mechanism

The false single-line `If` path is the amplifier [standard]:

1. `For(` with explicit `)` enters the `02:56C3` close/cleanup path before the
   control-flow handler records the loop continuation.
2. `For(` without `)` takes the `C=0` direct path at `02:5687`.
3. With a first body line of `If 0`, the loop immediately enters the
   single-statement false-`If` skip path (`if_isg_stmt_handler` at `38:6F63`,
   with skip/temporary-parser work through the page-38 statement evaluator).
4. In the direct-path case, that skip work is performed with a temporary parse
   range that advances every iteration. More iterations mean longer VAT/name
   and pointer scans, so the cost grows much faster than the explicit-paren
   version.

This is why `N=25` shows only a modest penalty while `N=100` shows a large one.
The omitted `)` saves a little cleanup work in the `If 1` control, but with
`If 0` first it changes the loop/skip interaction and leaks work into temporary
parser storage.

## Practical rule

When a `For(` loop body starts with a guard like `If not(condition)` or `If 0`,
write the closing `)`:

```ti-basic
For(I,1,N)
If A
...
End
```

Better still, avoid single-line false guards as the first statement of a hot
loop. Use `If ... Then` blocks when the body is structured, or invert the loop
so the common path does not repeatedly exercise the false-`If` skip scanner.
