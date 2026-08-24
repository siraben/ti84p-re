# Resident scratch RAM

Long-running assembly programs cannot treat the usual TI-OS work buffers as
anonymous memory while continuing to call arbitrary OS routines. Two OS
2.55MP traces directly overwrite `OP1`–`OP6`, `iMathPtr1`–`iMathPtr5`,
`textShadow`, and every byte of `saveSScreen`. The remaining advertised ranges
have subsystem owners that make them conditional, even where these traces did
not touch them. [confirmed]

The measurements are in `tools/data/scratch-ram-observations.csv`.
Regenerate a row set from a full-range TilEm trace with:

```sh
nix develop --command python3 tools/analyze_scratch_trace.py TRACE \
  --initial-port-5 0 --initial-port-7 0x81 \
  --scenario NAME --model ti84p --os-version 2.55MP --format csv
```

The initial selectors matter when a trace starts after TI-OS established its
normal mapping. A zero result means only that the scenario did not write the
range; it is not evidence that the range is safe.

## Observed clobbers [confirmed]

Both scenarios are direct compiled `Asm(` launches of the local `ti84-forth`
runtime. The second continues through cooked-input activity. Counts are memory
writes, followed by the number of distinct bytes touched.

| Buffer | Address range | Launch | Interactive input | Classification |
|---|---|---:|---:|---|
| `OP1`–`OP6` | `ram:8478`–`ram:84B9` | 218 / 44 | 824 / 44 | Unsafe across ordinary parser, VAT, and floating-point calls |
| `iMathPtr1`–`iMathPtr5` | `ram:84D3`–`ram:84DC` | 80 / 8 | 88 / 10 | Unsafe across VAT, graph, table, and link activity |
| `textShadow` | `ram:8508`–`ram:8587` | 442 / 128 | 1,097 / 21 | Unsafe with ordinary text display |
| `saveSScreen` | `ram:86EC`–`ram:89EB` | 2,304 / 768 | 3,072 / 768 | Unsafe in the normal launch state |
| `statVars` | `ram:8A3A`–`ram:8C4C` | 0 / 0 | 0 / 0 | Candidate only after `_DelRes`, with statistics and shell interrupts excluded |
| Table/solver workspace | `ram:91DC`–`ram:9301` | 0 / 0 | 0 / 0 | Candidate only while table, solver, finance, and graph-table contexts are excluded |
| `plotSScreen` | `ram:9340`–`ram:963F` | 0 / 0 | 0 / 0 | Unsafe when graph or buffered-display routines remain available |
| `appBackUpScreen` | `ram:9872`–`ram:9B71` | 0 / 0 | 0 / 0 | Candidate only in a controlled assembly context without app or menu transitions |

The traces include writers at `ram:1F37` and `07:51FA` for operand storage,
`07:4F70`–`07:4F82` for iMath pointers, and `01:617A` and `01:61C2` for text
state. The page-`0x3B` display-save loop writes every byte of `saveSScreen` at
its `3B:69C2` store. [confirmed]

Static ROM ownership disqualifies the zero-write rows as unconditional storage:
`_GrBufClr` clears `plotSScreen`; graph primitives consume it; table, solver,
finance, and graph-table code own the `ram:91DC` workspace; statistics routines
deposit named results in `statVars`; and app/menu state paths use
`appBackUpScreen`. [confirmed]

There is consequently no buffer in this table that remains stable while every
display, keyboard, VAT, archive, graph, table, statistics, app, error, APD,
link, and USB path is allowed. A runtime may borrow a conditional range only by
defining the excluded calls and contexts as part of its ABI.

## Conditional `saveSScreen` and `statVars` claims

Public TI-83 Plus documentation permits `saveSScreen` after `_DisableApd`, and
permits `statVars` after `_DelRes` when statistics code is excluded. A shell
interrupt, especially MirageOS's interrupt, adds another owner of `statVars`.
[standard]

Those conditions are not yet locally confirmed across `_GetKey`, the ON key,
error unwinding, and shell interrupts. The source fixture
`tools/fixtures/scratch_guard_probe.asm` and its TilEm macro
`tools/macros/scratch-guard-probe.macro` fill both
ranges, enter `_GetKey`, and check the guards. Its first automated launch
reached a TI-OS error before the fixture executed, so it supplies no result.
[hypothesis fixture]

## Page `0x83` during resident execution

Page `0x83` is OS state rather than a spare 16 KiB page. The two resident traces
add the following observations to the boot and expression traces documented in
[RAM pages](ram-pages.md):

| Scenario | Writes | Touched range |
|---|---:|---|
| Direct resident launch | 2,304 | `83:5A7E`–`83:5D7D` |
| Interactive resident input | 3,840 | `83:5A7E`–`83:5D7D` |

The range is the LCD/home-display capture area. Combining these runs with ROM,
boot, and expression evidence gives these known owners:

| Page-`0x83` range | Owner |
|---|---|
| `83:4000`–`83:4080` | App base-page staging [standard] |
| `83:4100`–`83:433A` | USB communication buffers [standard] |
| `83:4373`–`83:4390` | Expression-path block copy [confirmed] |
| `83:43D9`–`83:44BD` | Boot/home block copy [confirmed] |
| `83:577E`–`83:5A7D` | MathPrint previous-entry history [confirmed] |
| `83:5A7E`–`83:5D7D` | LCD/home-display capture [confirmed] |
| `83:5D7E`–`83:5DF2` | Additional boot/home writes [confirmed within that scenario] |

All holes are candidates, not safe ranges. Current coverage omits USB receive,
archive garbage collection, statistics, the program editor, app transitions,
APD, error dialogs, and third-party interrupts.

Selectors `0x82`–`0x87` alias one physical RAM page on 48 KiB ASICs. Pages
`0x84`–`0x87` still need forced read/write/hash probes on 128 KiB calculators;
an emulator's unused page is not hardware confirmation. [standard]

## Mapping a RAM page through bank A

The page-zero bcall dispatcher at `ram:2A2F` restores the caller's port-`0x06`
selector on ordinary return. During the bcall, however, the dispatcher maps its
own target into `0x4000`–`0x7FFF`, so a pointer into a borrowed bank-A page is
invalid. An OS error can also bypass caller-owned cleanup. [confirmed]

A bounded copy operation should save the selector and interrupt state, map the
page, copy, and restore before making another bcall:

```z80
    LD A,I
    PUSH AF             ; P/V records IFF2
    DI
    IN A,(0x0E)
    PUSH AF
    IN A,(0x06)
    PUSH AF

    XOR A
    OUT (0x0E),A
    LD A,0x83
    OUT (0x06),A

    ; Copy only. Do not call a bcall with a pointer into bank A.

    POP AF
    OUT (0x06),A
    POP AF
    OUT (0x0E),A
    POP AF
    JP PO,interrupts_were_disabled
    EI
interrupts_were_disabled:
```

Code running in bank A cannot use this sequence to map out its own instruction
stream. Keep interrupts disabled for the entire nonstandard mapping unless the
interrupt handler is proven independent of normal bank-A ROM. Restore both
ports even though port `0x0E` is ignored by TI-84 Plus and TI-84 Plus SE
hardware; doing so keeps the helper transparent and portable to related models.
