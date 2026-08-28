# TI-BASIC programming patterns

TI-BASIC performance depends on parser work, floating-point transfers, VAT
lookups, and display calls. This page collects the source-level decisions. The
full programs, traces, and BASIC/ASM fixtures are in
[TI-BASIC examples and ASM interop](sub-tibasic-examples.md).

## Choose work with fewer interpreter crossings

The statement loop at `38:59C5` dispatches every source statement. Structured
loops also maintain FPS and OPS records, and each variable access crosses the
VAT/value boundary. [confirmed]

| Source-level choice | Interpreter cost | Example |
|---------------------|------------------|---------|
| Keep loop bodies short | Fewer statement dispatches and parser scans per iteration | [Text animation](sub-tibasic-examples.md#text-animation-with-output) |
| Prefer list or matrix primitives | One parsed command can run an internal ROM loop | [Trace-backed list fixture](sub-tibasic-examples.md#trace-backed-examples) |
| Cache repeated list elements in scalars | Avoid repeated VAT lookup and list-element address calculation | [DFS list stack](sub-tibasic-examples.md#dfs-with-a-list-stack) |
| Keep graph drawing in the graph buffer | Avoid repeated home-screen formatting and LCD updates | [Graph-buffer visualization](sub-tibasic-examples.md#graph-buffer-visualization) |
| Use structured loops instead of hot `Goto` paths | Avoid repeated label rescans through `38:7600` | [Loop behavior](sub-tibasic.md#natural-loops-use-a-page-38-ops-record) |
| Include the optional `For(` closing parenthesis | Avoid the documented implicit-close parser trap | [`For(` parenthesis trap](sub-tibasic-for-paren.md) |

These are interpreter-cost rules, not cycle counts. Exact timing depends on the
program, data, display mode, and calculator speed.

## Preserve the BASIC caller for callbacks

TI-BASIC subprograms share variables and `Ans`, but preserve parser control in
a private frame. Use a small input/output convention and let BASIC perform the
`prgmNAME` call. [confirmed]

| Boundary | Supported pattern |
|----------|-------------------|
| BASIC → BASIC | Store inputs, call `prgmNAME`, then read shared variables or `Ans`. |
| BASIC → ASM | Call `Asm(prgmNAME)` and require the payload to return normally. |
| ASM → BASIC callback | Store a result or signal in `Ans`, return to BASIC, and let the wrapper call `prgmNAME`. |

The compiled launcher, negative public-bcall probes, and private-frame
comparison are documented under
[BASIC and ASM interop](sub-tibasic-examples.md#basic-and-asm-interop).
