# Tooling layout

Everything under `tools/` supports the wiki with reproducible evidence: the
Ghidra build, the checked symbol registries, the `ti84re` Python package, and
the probe sources, macros, and oracles the package consumes.

```text
tools/
├── build.sh              rebuild ti84.gpr from the local ROM (Ghidra headless)
├── setup-wiki-assets.sh  vendor KaTeX and pseudocode.js for mdBook
├── ghidra/               headless Ghidra pipeline scripts (*.java)
│   └── studies/          one-off inspection and decompilation scripts
├── symbols/              checked registries: names, bcalls, labels, types, SDK equates
├── ti84re/               Python package: ROM access, hardware models, emulators, analyzers
├── tests/                unittest suite mirroring the ti84re packages
├── js/                   MathPrint and graphing checks for web/ (Node)
├── oracles/              checked JSON evidence reports and test oracles
├── data/                 checked CSV observations cited by the wiki
├── macros/               headless TilEm macros
├── probes/               probe sources: Z80 asm, TilEm C adapters, MAME Lua, Wabbitemu C++
├── tibasic-samples/      tokenized TI-BASIC fixtures
├── badapple/             Bad Apple playback experiment assets
└── notes/                tooling guides (dynamic tracing, fixtures, MathPrint specs)
```

Local, gitignored inputs live directly under `tools/`: `rom.bin`
(the assembled OS 2.55MP image), `ti84_page00.bin`, and the `roms/` directory
holding the retail artifacts that `ti84re.rom.assemble_local_rom` validates.

## Running the Python tools

`ti84re` is a plain package, so put `tools/` on the module path once and run
modules with `-m`:

```sh
export PYTHONPATH=$PWD/tools        # `nix develop` sets this for you
python3 -m ti84re.link.describe_port profiles
python3 -m ti84re.rom.disassemble 0x3B --start 0x4000 --end 0x4040
```

Every module resolves repository locations through `ti84re.paths`
(`ROOT`, `TOOLS`, `SYMBOLS`, `ORACLES`, `DATA`, `MACROS`, `PROBES`,
`DEFAULT_ROM`); nothing depends on the current working directory.

## Package map

| Package | Contents |
|---------|----------|
| `ti84re.rom` | ROM image access, bcall tables, linear disassembly (`z80dasm`), I/O and literal scans, provenance manifests |
| `ti84re.boot` | retail boot page hardware sequence, dormant LCD diagnostic, BootFree comparison |
| `ti84re.hardware` | ASIC, bus timing, execution protection, interrupts, keypad, LCD, MD5, mapper, timers, USB models, physical probe frames |
| `ti84re.flash` | Flash device model, gate and command scans, trace decoding, replay, GC journal, guarded fixtures, certificate rebuild |
| `ti84re.link` | two-wire link port model, TI-8x backup files, link-to-Flash staging |
| `ti84re.trace` | TilEm trace resolution to paged addresses, hardware-trace iterators, LCD replay, trace analyzers |
| `ti84re.emulators` | shared probe CLI plumbing plus `wabbitemu`, `tilem`, and `mame` subpackages (adapters, oracles, guarded runners) |
| `ti84re.tibasic` | tokenized sample programs, headless smoke runs, interpreter coverage and error-provenance reducers |
| `ti84re.tifiles` | deterministic TI program, group, and AppVar file builders |
| `ti84re.mathprint` | ROM extraction for `web/mathprint`, record capture, saturation audit, parity and fuzz checks |
| `ti84re.graphing` | circle drawing model and function-mode regraph reducer |
| `ti84re.community` | ticalc.org archive inventory, community bcall audit, Flash App headers |
| `ti84re.wiki` | mdBook output validators, token-table generator, WikiTI dump, snippet checks |
| `ti84re.badapple` | Bad Apple injection, music encoding, link-port audio extraction |

Module names follow a fixed vocabulary inside each package:

- a bare name (`lcd_controller.py`, `port.py`) is an importable model or decoder;
- `describe_*` is a read-only CLI over such a model;
- `analyze_*` reduces ROM bytes or traces to a checked report;
- `build_*` produces a fixture, probe binary, or TI file;
- `run_*` executes a guarded emulator probe and writes a manifest.

## Tests

```sh
cd tools && python3 -m unittest discover -s tests -t .
node tools/js/test-mathprint.js
node tools/js/test-graph-coordinate.js
node tools/js/test-graphing-demo.js
```

Tests that need the local ROM, `z80dasm`, or the retail artifacts under
`tools/roms/` error out when those are absent; `nix build` runs the
ROM-independent subset.

## Ghidra build

`build.sh` locates `analyzeHeadless`, regenerates `symbols/bcall_targets.txt`,
then runs the `ghidra/` scripts in order with `symbols/` as their data
directory. `ghidra/studies/` holds ad-hoc scripts that are run by hand from the
Script Manager or with `-scriptPath tools/ghidra/studies`.
