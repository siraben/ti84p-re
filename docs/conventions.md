# Conventions & Methodology

How to read these notes, and how they were produced.

## Suggested reading order

1. [Overview](00-system-overview.md) — the four pillars and the system through-line.
2. [Subsystem Map](10-subsystem-map.md) — see the whole API surface at once.
3. Substrate: [Memory Map](01-memory-map.md) → [Paging](02-paging.md) → [The bcall Mechanism](03-bcall-mechanism.md) → [Interrupts](04-interrupts.md).
4. Pick a core subsystem ([Floating-Point](06-floating-point.md), [VAT](05-variables-vat.md), [Tokenizer/TI-BASIC](07-tokenizer-basic.md), [Display](08-display-lcd.md)…), then its **feature deep-dive** (`sub-*`).
5. [Glossary](glossary.md) for any unfamiliar term.

## Address notation

- **`pp:addr`** — flash page `pp` (`00`–`3F`), logical address `addr`. Banked pages run in the `4000–7FFF` window, so e.g. `_PutS` at `01:5C39` means page 1, address `0x5C39`. Example: `3D:6745`.
- **`ram:addr`** — page 0 (the always-mapped kernel) and the RAM window; Ghidra keeps page 0 in its `ram` space, so `ram:229E` ≡ `00:229E`.
- **`page_pp:addr`** — the same as `pp:addr`, written in Ghidra's overlay-space form (`page_38:4000`). Used where it matches the tool output.
- A bare `0x….` (no page) is a **RAM data address** (e.g. `flags` `0x89F0`).
- **bcall ID ≠ address.** A bcall has an *ID* (the 2-byte word after `rst 28h`, e.g. `_FindSym` = `42F4h`) and a *body address* (`00:0E65`). The ID indexes the jump table; it is not where the code lives.

## Confidence flags

Every non-obvious claim is tagged:

| Flag | Meaning |
|------|---------|
| **[confirmed]** | Directly observed in the disassembly/decompiler of this ROM. |
| **[standard]** | Matches the publicly-documented TI-83+/84+ architecture and is consistent with what we see, but not every byte was traced. |
| **[hypothesis]** | Inferred / not yet verified — treat with caution. |

Some early deep-dive docs use shorthand `[C]`/`[H]`/`[I]` ≈ `[confirmed]`/`[hypothesis-ish]`/`[inferred]`; read them against this three-tier scheme.

## Function naming

- **`_CamelCase`** — an official TI bcall/equate name (from `ti83plus.inc` or the TI SDK), e.g. `_FindSym`, `_FPAdd`. High confidence.
- **`snake_case`** — a name **inferred during this RE** from a routine's behavior (which named routines it calls, which RAM/ports it touches), e.g. `findsym_scan`, `fp_normalize`. Accurate in aggregate; any single low-level helper name is a best-effort guess.

## Math notation

Formulas are written in LaTeX and rendered by **KaTeX** (offline, client-side): `$…$` for inline math and `$$…$$` (or `\[…\]`) for display. KaTeX skips `<code>`/`<pre>`, so `$`-prefixed hex like `$1A2F` inside code blocks is left untouched.

> **Escaping caveat:** mdBook runs markdown *before* the client-side KaTeX pass, and markdown strips a backslash before ASCII punctuation. So inside `$…$`/`$$…$$` you must **double** those escapes — write `\\,` (thin space), `\\%` (percent), `\\\\` (matrix/array row break), `\\{`/`\\}` — otherwise KaTeX receives `,`/`%`/`\` and mis-renders (a bare `%` even comments out the rest of the formula). Backslash-before-letter macros (`\frac`, `\sum`, `\sqrt`, …) are safe as-is. Fenced ` ```pseudocode `/` ```mermaid ` blocks are verbatim and need no doubling. **Algorithms** are written as ` ```pseudocode ` blocks in [pseudocode.js](https://github.com/SaswatPadhi/pseudocode.js) `\begin{algorithm}` syntax and typeset client-side. Diagrams use Mermaid (` ```mermaid `) and render to SVG. See the repository `flake.nix`/`book.toml` for how the assets are vendored.

## How this RE was produced

- **The Ghidra database** is rebuilt from the ROM by `tools/build.sh` (a 10-stage headless pipeline). It loads all 64 flash pages (page 0 + overlays at `4000`), then resolves and names routines. 100% of the 2413 functions are named.
- **bcall table resolution.** The main jump table page was found by *scoring* all 64 flash pages: for each candidate, count how many of the known bcall IDs produce a valid `(addr, page)` entry. Page 0x3B scored 447/535 (the runner-up only 124) for the `0x4xxx` table and is cross-checked against the documented RST shortcuts (all six matched). Historical `0x8xxx`/page-0x3F candidates exist in generated files, but their targets are not currently exposed as functions by the live Ghidra/MCP DB.
- **Decompiler caveats.** Ghidra's Z80 decompiler mis-renders some idioms — `SET b,(IY+d)` flag ops, the `CALL cross_page_jump` (`2b09`) trampolines, and register-passed arguments on banked pages. Where the decompiler is unreliable the notes are grounded in the raw disassembly (and several deep-dives used a small custom Z80 decoder over the ROM to verify addresses byte-exactly).
- **Parallel multi-agent passes.** The feature deep-dives (`sub-*`) and the final 100%-naming pass were produced by multiple agents working on isolated copies of the database, each owning a disjoint set of pages, then merged.

See the repository `README.md` for the exact build pipeline and tooling.
