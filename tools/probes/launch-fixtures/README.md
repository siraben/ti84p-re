# Compiled-program launch boundaries

These fixtures test the internal-size limit in the compiled `BB 6D` program
path. Each link file contains a `ProgObj` whose data starts with `BB 6D`, a
one-byte `RET` payload, and zero padding. A small `Asm(prgmNAME)` wrapper invokes
each compiled object through `_ExecutePrgm`.

## Build

SPASM assembles the payload at `0x9D95`. The Python builder pads and packages it
as three TI-83+/84+ link files. The internal size includes the two-byte `BB 6D`
marker. It excludes the variable's two-byte size word.

```sh
nix develop -c python3 tools/probes/launch-fixtures/build.py \
  --out-dir /tmp/launch-boundary-fixtures
```

The `B1FFF`, `B2000`, and `B2001` objects have internal sizes `0x1FFF`,
`0x2000`, and `0x2001`. Their `A1FFF`, `A2000`, and `A2001` wrappers sort first
in the PRGM menu. The native payload lengths after the marker are 8189, 8190,
and 8191 bytes.

## Run

Set `TILEM` to the local headless TilEm build that loads command-line link files
before starting a macro. The runner boots a clean calculator for each fixture
pair, runs the wrapper, records a full instruction trace, and resolves coverage
through `tools/ti84re/trace/resolve.py`. It checks the launch anchors against raw
logical PCs because command-line transfer occurs before tracing starts, so the
trace may not contain the initial bank-selector writes needed to label
`ram:9D95`.

```sh
nix develop --command python3 tools/probes/launch-fixtures/run.py \
  --tilem "$TILEM" \
  --rom tools/rom.bin \
  --fixtures /tmp/launch-boundary-fixtures \
  --out-dir /tmp/launch-boundary-results \
  --keep-trace
```

An accepted case must reach `_ExecutePrgm` at `07:5758`, the `_InsertMem` call
site at `07:578D`, the payload handoff at `07:57B4`, and `ram:9D95`. A rejected
case must branch to the `E_Invalid` shim at `ram:2729` before the call site.

## Confirmed result

| Internal size | Native payload | Observed path |
|---------------|----------------|---------------|
| `0x1FFF` | 8189 bytes | accepted |
| `0x2000` | 8190 bytes | accepted |
| `0x2001` | 8191 bytes | `ERR:INVALID` |

The threshold follows the unsigned subtraction at `07:577B`–`07:5781`.
All three rows were run on TI-OS 2.55MP under TilEm x4 with base-ROM SHA-256
`dbb47afae091ab36f9abe74e32083013fbeff3d7e0516bbf5d1abf4ee57adc09`.
The accepted cases reach `07:578D`, `07:57B4`, and logical `0x9D95`; the
rejected case reaches logical `0x2729` without those three addresses.
Machine-readable fixture and trace hashes are in
`tools/data/launch-boundary-results.csv`. [confirmed]

The complete-image hash identifies the BootFree 11.259 variant. Flash page
`0x07`, which contains the measured launcher, is byte-identical to the
canonical retail analysis image. These traces make no retail-boot claim.
[confirmed]

Dynamic acceptance still depends on enough free RAM for the execution copy.
[confirmed]
