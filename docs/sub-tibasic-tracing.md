# TI-BASIC dynamic tracing

TI-BASIC coverage combines exhaustive local models with natural calculator
traces. The models answer “did every input to this bounded decision get
classified?”; traces answer “which decisions did these complete programs reach
with real parser, VAT, floating-point, and display state?” Neither answer alone
is whole-interpreter coverage.

## Evidence layers

| Layer | Establishes | Does not establish |
|-------|-------------|--------------------|
| ROM signature | The modeled instructions are still the expected OS 2.55MP bytes | Meaning of every surrounding routine |
| Finite model | Every state in a declared finite domain has an outcome | Arbitrary sequences or external RAM/stack state |
| Natural trace | A real program reached an instruction and took a branch outcome | Feasibility of unobserved outcomes |
| LCD assertion | The program produced the expected visible result | Which internal path was uniquely responsible |

`tools/analyze_tibasic_coverage.py` refuses a ROM whose SHA-256 differs from
the pinned OS 2.55MP image, then verifies short byte signatures at every modeled
decision family. [confirmed]

## Exhaustive finite models

The checked report exhausts 591,360 states and 45 semantic outcomes:

| Model | Exhausted states | Outcomes | Boundary |
|-------|-----------------:|---------:|----------|
| Encoded token width | 256 | 2 | Lead-byte membership, not second-byte validity |
| Statement delimiter | 256 | 4 | Byte classification, not refill faults |
| Token scan step | 256 | 4 | One step, not arbitrary stream length |
| Block matcher transition | 524,288 | 10 | Every 16-bit depth over eight decision-equivalent token classes |
| Extended grammar fold | 256 | 2 | `CP F2h`/`ADD 12h`, not later handlers |
| Precedence handler family | 65,536 | 3 | Grammar class × selector byte, not recursive handler state |
| Command finalization gate | 256 | 5 | First page-02 gate only |
| Control-flow table bounds | 256 | 15 | Index validation, not the 13 handler bodies |

The block model uses token equivalence classes because the ROM performs the
same comparisons for every non-control byte. It still enumerates all 65,536
values of the 16-bit `DE` depth, including the zero and increment-wrap boundaries. This
is exhaustive over the stated local transition, not a depth limit of 255.

Z3 minimizes one representative per semantic outcome after exhaustive
enumeration establishes the partition. Z3 is not being presented as a proof of
the entire Z80 routine or of arbitrary token streams.

## Diverse natural corpus

Six fixtures cover distinct interpreter behaviors without committing redundant
raw traces:

| Case | Distinct behavior | Visible oracle |
|------|-------------------|----------------|
| `hello` | straight-line statement, quoted string, `Disp` | `HELLO, WORLD`; `Done` |
| `factorial` | `Prompt`, scalar stores, `For(`/`End`, FP multiplication | input `5`; result `120` |
| `data` | two-byte list tokens, literal/store, built-in list fold | sorted/cumulative lists; `14` |
| `dfs` | nested `While`, `If ... Then`, `For`, list-backed stack | traversal `1,3,2,4`; visited list |
| `callabi` | nested BASIC call, shared scalar/list/`Ans`, `Return` | `11`; `{2 4 9}`; `11` |
| `callstop` | nested BASIC call and nonlocal `Stop` | `BEFORE`; `STOP`; no `AFTER` |

The current traces contain 25,750,215 instruction records. Across 26 declared
conditional branch sites, they observe 18 of 52 possible outcomes at 15 sites.
`DFS` supplies the block-scanner outcomes; the other programs deliberately
exercise different semantic state even when their selected branch outcomes
overlap. No declared branch transition had an unclassifiable successor.
[confirmed]

An exact Z3 set cover over both observed branch outcomes and semantic feature
tags retains all six cases. That result is useful: removing any one would lose
a distinct behavior such as quoted-string display, prompted arithmetic, a list
fold, nested blocks, `Return`, or `Stop`. The larger fixture library remains
available for targeted subsystem work, but it is not described as the minimum
TI-BASIC coverage corpus.

The selected traces total about 1.27 GB, so only their SHA-256 digests, record
counts, outcome counts, and minimization result are checked in. The JSON report
is about 20 KB.

## Reproduce the report

Generate the source/token/link fixtures first:

```sh
tools/tibasic_samples.py --write-dir tools/tibasic-samples
```

The TilEm binary must support loading command-line `.8xp` files before the
macro starts. Run the six cases while retaining their temporary traces:

```sh
TILEM=/path/to/patched/tilem2
python3 tools/tibasic_smoke.py \
  --tilem "$TILEM" --rom tools/rom.bin \
  --out-dir /tmp/tibasic-coverage --keep-trace \
  --case hello --case factorial --case data \
  --case dfs --case callabi --case callstop
```

The smoke runner checks trace anchors and named LCD crop regions before the
coverage analyzer sees a trace. Build the compact report through the Nix shell
so `z80dasm` and Z3 are pinned:

```sh
nix develop -c python3 tools/analyze_tibasic_coverage.py \
  --trace hello=/tmp/tibasic-coverage/hello.trace \
  --trace factorial=/tmp/tibasic-coverage/factorial.trace \
  --trace data=/tmp/tibasic-coverage/data.trace \
  --trace dfs=/tmp/tibasic-coverage/dfs.trace \
  --trace callabi=/tmp/tibasic-coverage/callabi.trace \
  --trace callstop=/tmp/tibasic-coverage/callstop.trace \
  --output tools/tibasic-coverage.json
```

Delete the temporary traces after regeneration. They are reproducible evidence,
not source assets.

## Reading gaps honestly

The current trace overlay does not enter the modeled command-finalization or
page-33 table-bound branches. In particular, `factorial` and `dfs` execute
stored-program loops without reaching the static `33:435F` path. The report
therefore leaves the exact stored-program loop-handler transition open instead
of treating the static dispatcher as dynamically confirmed.

Other open dimensions include arbitrary token-stream length, recursive grammar
paths, quoted-string contents, error unwinding, loop-record field layout,
computed handler destinations, and the internal state spaces of VAT, lists,
floating point, graphing, and display code.

The next useful coverage expansion is not “add more examples.” It is:

1. identify one specific unobserved branch or state boundary;
2. construct the smallest natural program expected to distinguish it;
3. confirm the screen or RAM oracle;
4. add the trace only if Z3 shows that it contributes a new branch outcome or
   semantic feature; and
5. update the relevant interpreter explanation with the newly established
   transition.

Lower-level trace formats and memory-write decoding are documented in
`tools/dynamic-tracing.md`.
