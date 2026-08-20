# Conventions and evidence

This page defines the notation, evidence labels, and naming conventions used
throughout the wiki.

## Suggested reading order

1. [System overview](system-overview.md) introduces the machine, OS, and evidence model.
2. [Subsystem map](subsystem-map.md) shows the major services and their dependencies.
3. [Memory map](memory-map.md), [Paging](paging.md), [The bcall mechanism](bcall-mechanism.md), and [Interrupts](interrupts.md) cover the shared architecture.
4. Continue with a core subsystem such as [Floating point](floating-point.md), [Variables and the VAT](variables-vat.md), [Tokenizer and TI-BASIC tokens](tokenizer-basic.md), or [Display and LCD](display-lcd.md), followed by its linked deep dives.
5. [Glossary](glossary.md) for any unfamiliar term.

## Address notation

- `pp:addr` — Flash page `pp` (`00`–`3F`) and logical address `addr`. Banked pages run in the `0x4000`–`0x7FFF` window, so `_PutS` at `01:5C39` means page `01`, address `0x5C39`.
- `ram:addr` — page 0 (the always-mapped kernel) and the RAM window; Ghidra keeps page 0 in its `ram` space, so `ram:229E` ≡ `00:229E`.
- Ghidra's overlay space writes flash addresses as `page_pp:addr` (e.g. `page_38:4000`); the wiki normalizes these to the short `pp:addr` form, so `page_38:4000` is written `38:4000`.
- A bare `0x….` (no page) is a RAM data address or an unpaged value (e.g. `flags` `0x89F0`, the bcall-ID ranges `0x4xxx`/`0x8xxx`, a page number like `0x3B`).
- **bcall ID ≠ address.** A bcall has an ID (the 2-byte word after `rst 28h`, such as `_FindSym` = `0x42F4`) and a body address (`00:0E65`). The ID indexes the jump table; it is not where the code lives.

## Confidence flags

Every non-obvious claim is tagged:

| Flag | Meaning |
|------|---------|
| [confirmed] | Directly observed in this ROM's disassembly, decompiler, raw bytes, generated database, or a labeled execution trace. |
| [standard] | Matches the publicly-documented TI-83+/84+ architecture and is consistent with the disassembly, but not every byte was traced. |
| [hypothesis] | Inferred / not yet verified — treat with caution. |

## Function naming

- `_CamelCase` — an official TI bcall/equate name (from `ti83plus.inc`, the full 2007 TI-83 Plus SDK equates file, or the TI SDK), e.g. `_FindSym`, `_FPAdd`. High confidence.
- `snake_case` — a name inferred from a routine's behavior, including its callees and RAM or port accesses, such as `findsym_scan` or `fp_normalize`. Any individual low-level helper name remains a best-effort interpretation.

The rebuilt Ghidra project keeps each kind of name in a separate checked registry:

- `tools/names.txt` contains function entries. Its importer disassembles the entry and creates a function.
- `tools/labels.txt` contains ROM data and internal code-entry labels. Rows marked `entry` seed and preserve disassembly without creating an overlapping function.
- `tools/ram.txt` contains RAM symbols, including official SDK equates and carefully named inferred state.
- `tools/ports.txt` contains I/O-port symbols.
- `tools/poffsets.txt` contains reviewed base-plus-offset references. These make an operand such as `mathprintArenaState + 0x0D` render as a structure member without inventing a second global name for the field address.

`tools/ty_regions.txt` applies the C layouts built by `BuildTypes.java`. The prose can therefore use expressions such as `table_value_cache.band[1].value[row]` once it introduces the typed base and its concrete address. A physical boundary, trace target, or byte-level proof still keeps its concrete address. [confirmed]

## Math notation

Formulas are written in LaTeX and rendered by KaTeX (offline, client-side): `$…$` for inline math and `$$…$$` for display. Algorithms render as pseudocode blocks and data/control-flow diagrams as Mermaid.

## Evidence and reproducibility

- The Ghidra database is rebuilt from the ROM by `tools/build.sh` (a 15-stage reproducible pipeline around Ghidra's headless analyzer). It loads all 64 flash pages (page 0 + overlays at `4000`), then resolves routines, applies function and data symbols, and installs the checked C layouts and offset references.
- **Local ROM trust boundary.** `tools/assemble_local_rom.py --check` validates the exact ignored base-ROM and AppVar hashes without writing output. Its reusable `tools/rom_assembly.py` library decodes each TI variable container, verifies its checksum, type, name, flags, duplicate length fields, internal 16 KiB size, and payload hash, then requires the assembled-ROM hash. This proves which bytes the analysis uses; it does not prove that the files were captured from a physical calculator. The pinned base already contains the `D84PBE1.8Xv` page-`3F` payload byte for byte. Only `D84PBE2.8Xv`, installed at page `2F`, changes the base image (8,615 bytes). [confirmed]
- **bcall table resolution.** The main jump table page was found by *scoring* all 64 flash pages: for each candidate, count how many of the known bcall IDs produce a valid `(addr, page)` entry. Page 0x3B scored highest for the `0x4xxx` table — more known bcall IDs resolve to a valid `(addr, page)` entry there than on any other page — and is confirmed by the documented RST shortcuts (all six matched) and by every entry resolving and live-confirming once 0x3B is applied. `0x8xxx` bcall IDs index 87 populated retail boot-table entries on page `3F`; several USB entries target page `2F`. The local `rom.bin` is assembled from the patched base plus the retail `D84PBE1.8Xv` and `D84PBE2.8Xv` payloads. `tools/bcalls8x_targets.txt` contains the 83 byte-resolved bodies with public SDK names; the remaining four entries have project-inferred names. The resolver rejects these targets when page `3F` has a BootFree prefix.
- **Decompiler caveats.** Ghidra's Z80 decompiler can mis-render `SET b,(IY+d)` flag operations, `CALL cross_page_jump` (`ram:2B09`) trampolines, and register-passed arguments on banked pages. Raw disassembly and ROM bytes are authoritative for these cases.

See the repository `README.md` for the exact build pipeline and tooling.
