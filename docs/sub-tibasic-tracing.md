# TI-BASIC dynamic tracing

TI-BASIC coverage combines exhaustive local models, natural calculator traces,
and provenance-labeled probes. The models classify bounded decisions. Natural
traces establish program reachability. Probes distinguish remaining outcomes
without presenting prepared state as a natural language path. None of these
layers is whole-interpreter coverage.

## Evidence layers

| Layer | Establishes | Does not establish |
|-------|-------------|--------------------|
| ROM signature | The modeled instructions are the expected OS 2.55MP bytes | Meaning of every surrounding routine |
| Finite model | Every state in one declared finite domain has an outcome | Arbitrary streams or caller-owned RAM and stack state |
| Natural trace | A stored TI-BASIC program reaches an outcome with ordinary parser state | Feasibility of an unobserved outcome |
| Public-bcall probe | Exact ROM execution reaches a public ABI boundary | Natural TI-BASIC reachability of the supplied register value |
| Internal-entry probe | Exact ROM execution distinguishes a selected internal state | A supported ABI or natural caller for that state |
| RAM or LCD assertion | The fixture produces its expected machine or visible result | Which internal path is uniquely responsible |

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

## Coverage by provenance

The report declares 26 branch sites and both outcomes at each site. Natural
programs reach 34 of those 52 outcomes. Public-bcall probes add the four
page-33 bounds outcomes. Internal-entry probes add the remaining 14 outcomes.
The union reaches 52 of 52, but only the first number describes natural
TI-BASIC reachability. [confirmed]

```mermaid
flowchart LR
    N["Natural TI-BASIC<br/>34 / 52 outcomes"] --> U["Declared outcome union<br/>52 / 52"]
    B["Public bcall probes<br/>4 additional outcomes"] --> U
    I["Internal-entry probes<br/>14 additional outcomes"] --> U
    F["Eight finite models<br/>591,360 states"] --> R["Compact report"]
    U --> R
    R --> Z["Exact Z3 set cover<br/>15 outcome traces"]
```

The per-provenance counts in the JSON are 34, 8, and 18 because wrappers share
ordinary grammar outcomes. Those counts overlap. The additional-outcome counts
in the diagram describe what each probe layer contributes after the preceding
layer. No successor at a declared branch is unclassified. [confirmed]

### Natural programs

Seven successful fixtures cover distinct interpreter behaviors:

| Case | Distinct behavior | Oracle |
|------|-------------------|--------|
| `hello` | straight-line statement, quoted string, `Disp` | LCD text |
| `factorial` | `Prompt`, scalar stores, `For(`/`End`, FP multiplication | LCD result `120` |
| `data` | two-byte list tokens, literal/store, built-in list fold | lists and sum on the LCD |
| `dfs` | nested `While`, `If ... Then`, `For`, and list-backed stack | traversal and visited list |
| `callabi` | nested BASIC call, shared scalar/list/`Ans`, `Return` | returned scalar and list state |
| `callstop` | nested BASIC call and nonlocal `Stop` | absence of the post-call line |
| `branchmatrix` | `Else`, `Repeat`, nested blocks, and an omitted string quote | `A5h` at `plotSScreen` (`0x9340`) |

`missingend` and `terminalif` add natural end-of-input error boundaries. They
exercise the two carry returns that successful block structure cannot reach.
The report marks both traces with `termination: error`. [confirmed]

### Probe outcomes

Three public-bcall probes call `grf_435f = 5140h` with an input below the table,
inside the table, and at its upper boundary. They cover both outcomes at
`33:436D` and `33:4372`. These are public ABI executions, not stored-program
loop transitions. [confirmed]

Eight internal-entry probes cover four command-finalization classes and four
grammar states. They map the required ROM page, enter the selected routine from
RAM, and let the exact ROM execute the branch. `cmdbad` combines the safe
implicit-end case with the invalid class, which removes one redundant trace.
These probes establish branch behavior only; they do not establish a natural
caller or a supported interface. [confirmed]

Across all 20 traces, the report records 84,936,043 instructions. The raw files
total about 4.18 GB. Only SHA-256 digests, counts, outcomes, provenance, and the
33 KB report are checked in. Exact outcome-only set cover retains 15 traces.
The semantic-feature cover retains all 20 because the five omitted from the
outcome cover provide distinct successful behaviors. [confirmed]

## Reproduce the report

Generate the source/token/link fixtures first:

```sh
tools/tibasic_samples.py --write-dir tools/tibasic-samples
```

The TilEm binary must support loading command-line `.8xp` files before the
macro starts. Run the natural cases while retaining their temporary traces:

```sh
TILEM=/path/to/patched/tilem2
python3 tools/tibasic_smoke.py \
  --tilem "$TILEM" --rom tools/rom.bin \
  --out-dir /tmp/tibasic-coverage --keep-trace \
  --case hello --case factorial --case data \
  --case dfs --case callabi --case callstop \
  --case branchmatrix --case missingend --case terminalif
```

Run the probe cases in the same output directory:

```sh
python3 tools/tibasic_smoke.py \
  --tilem "$TILEM" --rom tools/rom.bin \
  --out-dir /tmp/tibasic-coverage --keep-trace \
  --case cflowlow --case cflowhigh --case cflowvalid \
  --case cmdclose --case cmdopen --case cmdunit --case cmdbad \
  --case gramlow --case gramhigh --case gramflag --case gramnonzero
```

The natural branch matrix uses a RAM marker instead of an image crop. The
probe cases use resolved trace anchors. Existing user-facing samples retain LCD
oracles where the displayed result is part of the behavior.

Build the compact report through the Nix shell so `z80dasm` and Z3 are pinned.
The checked command passes all 20 `LABEL=PATH` pairs; the complete ordered label
list is the `dynamic.traces` array in `tools/tibasic-coverage.json`.

```sh
set --
for label in \
  hello factorial data dfs callabi callstop \
  branchmatrix missingend terminalif \
  cflowlow cflowhigh cflowvalid \
  cmdclose cmdopen cmdunit cmdbad \
  gramlow gramhigh gramflag gramnonzero
do
  set -- "$@" --trace "$label=/tmp/tibasic-coverage/$label.trace"
done
nix develop -c python3 tools/analyze_tibasic_coverage.py "$@" \
  --output tools/tibasic-coverage.json
```

Delete the temporary traces after regeneration. They are reproducible evidence,
not source assets.

## Reading gaps honestly

Full coverage here means both outcomes at the 26 declared sites. It does not
mean full control-flow coverage of the interpreter. Natural programs still lack
witnesses for 18 declared outcomes, and internal-entry probes do not prove that
their prepared states have natural callers.

`factorial`, `dfs`, and both `For(` benchmark spellings do not enter `02:5676`
or `33:435F`. The exact stored-program loop-handler transition therefore
remains open. Other open dimensions include arbitrary token-stream length,
recursive handler bodies, error unwinding, loop-record field layout, computed
handler destinations, and the internal state spaces of VAT, lists, floating
point, graphing, and display code.

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
