---
name: ti84-re-writing
description: Apply the TI-84 reverse-engineering wiki writing and notation standards. Use when Codex edits, reviews, audits, or creates Markdown docs in this repository; when checking prose voice, sentence-case headings, confidence flags, address notation, bcall IDs, inferred routine names, Z80 snippets, pseudocode, Mermaid, KaTeX, mdBook mechanics, or README/SUMMARY documentation style.
---

# TI-84 RE writing

Use this skill as the authoring standard for TI-84 reverse-engineering wiki
pages. It covers prose voice, page structure, evidence standards, project
notation, and mdBook-sensitive markup.

## Workflow

1. Locate the repository root with `git rev-parse --show-toplevel`.
2. Identify the target docs and adjacent pages that may need reconciliation.
3. Audit before editing. Check structure, prose, evidence, notation, confidence
   flags, code fences, and build-sensitive markup.
4. Edit narrowly. Preserve technical claims unless the cited evidence supports a
   correction.
5. Run `git diff --check` and the repository build. Prefer `nix build` when the
   repo uses it.
6. Report changed files, validation commands, and any remaining convention risk.

## Prose voice

- Lead with what a thing is and does, then give evidence.
- Use negation only to correct an interpretation that the bytes, disassembly, or
  tool output plausibly suggest. Otherwise state the positive fact.
- Do not narrate the history of the RE effort. Avoid phrases such as "an earlier
  pass", "turned out", "in fact", "is real, not a mis-decode", and "grounding
  shows". Write the bytes and what they mean.
- Use active voice. Prefer "`_FindSym` scans the VAT" over "the VAT is scanned."
  Passive voice is acceptable only when the actor is unknown or irrelevant.
- Use present tense for ROM behavior. Use past tense only for the RE method when
  the method itself matters.
- Do not use first person. Avoid "we" and "I".
- Address the reader as "you" only in how-to-read or build instructions.
- Keep sentences short. Split sentences over about 25 words unless the technical
  structure genuinely needs one sentence.
- Remove padding: "essentially", "basically", "sort of", "in order to", "it
  should be noted that".
- Do not use "easy", "simple", "just", "obviously", or "of course" to describe
  ROM behavior.

## Structure

- Keep one topic per page. A page should answer one subsystem or mechanism
  question. Put feature detail in a `sub-*.md` deep dive and link to it.
- Start with a 1-3 sentence overview before the first heading.
- Use sentence case for page titles and headings: "Memory map", not "Memory
  Map". Keep acronyms and proper nouns capitalized: VAT, LCD, TI-BASIC,
  MathPrint, API.
- Keep a page H1 and its `docs/SUMMARY.md` entry aligned in sentence case and
  core title. The H1 may include a section number or parenthetical the TOC omits.
- Do not put links inside headings. Leave a blank line after each heading.
- Use tables for enumerations: routines, IDs, type bytes, bit layouts, ports.
- Use prose for mechanisms.
- Use `pseudocode` fences for algorithms and `mermaid` fences for control/data
  flow diagrams.
- Use short bulleted lists when items are parallel.
- Do not make a table dump the whole article. Explain what the table means.

## Naming and notation

- Define a term on first use, then use the same term throughout the page.
- Assume readers know Z80 and calculator basics. Define TI-specific terms such
  as bcall, VAT, OP1, and TIFloat, and link to `docs/glossary.md` when useful.
- Official TI bcall/equate names use `_CamelCase`, such as `_FindSym` and
  `_FPAdd`.
- Inferred routine names use `snake_case`, such as `findsym_scan` and
  `fp_normalize`.
- A bcall has an ID and a body address. The ID is the 2-byte word after `rst
  28h`, such as `_FindSym = 42F4h`; it is not where the code body lives.
- Use `pp:addr` for flash page plus logical address, such as `3D:6745`.
- Use `ram:addr` for page 0 or the RAM window when Ghidra uses the `ram` space,
  such as `ram:229E`.
- Use `page_pp:addr` only when matching Ghidra overlay-space output, such as
  `page_38:4000`.
- Use bare `0x....` for RAM data addresses or unpaged values, such as `flags`
  at `0x89F0`.
- Be consistent about contractions, serial commas, and units within a page.

## Evidence and confidence

Ground every non-obvious claim.

| Flag | Meaning |
|------|---------|
| `[confirmed]` | Directly observed in this ROM's disassembly, decompiler output, byte decode, or generated database. |
| `[standard]` | Publicly documented TI-83+/84+ architecture that is consistent with the ROM, but not traced byte-for-byte in the current page. |
| `[hypothesis]` | Inferred or not yet verified. Treat it as unstable. |

- Cite the address, bcall ID, RAM label, port, table, or source that anchors the
  claim.
- Keep evidence close to the claim. Tables may use an Evidence column; prose
  should cite addresses inline.
- If part of a mechanism is decoded and part is open, name the exact gap.
- Reconcile older pages when a new finding changes them.
- Keep source types separate. Do not blur ROM-confirmed facts with WikiTI,
  Tilem, SDK, emulator, or inferred evidence.
- Some early deep dives use shorthand `[C]`, `[H]`, or `[I]`. Treat those as
  legacy approximations of `[confirmed]`, `[standard]`, and `[hypothesis]`, and
  prefer the full flags in new prose.

## Mechanics

- Code blocks must have language tags. Z80 assembly uses `z80`.
- Math uses KaTeX: `$...$` inline and `$$...$$` for display math.
- Inside math, double backslash-before-punctuation escapes because mdBook strips
  one pass before KaTeX. Write `\\,`, `\\%`, `\\\\`, `\\{`, and `\\}`.
- Backslash-before-letter math macros such as `\frac`, `\sum`, and `\sqrt` are
  safe as-is.
- `pseudocode` and `mermaid` fences are verbatim. They do not need doubled
  escapes.
- Mermaid diagrams render to SVG.
- Check links and anchors after heading edits.

## Methodology language

Use method details only when they help a reader verify or reproduce a claim.
Otherwise describe the machine behavior.

Acceptable method claims:

- The Ghidra database is rebuilt from the ROM by `tools/build.sh`.
- The ROM is loaded as page 0 plus banked overlays at `4000`.
- Bcall table claims distinguish IDs from body addresses.
- Ghidra's Z80 decompiler can mis-render `SET b,(IY+d)`, cross-page trampolines,
  and register-passed arguments on banked pages.
- Raw disassembly or direct ROM byte decoding may supersede decompiler output.

Avoid method history:

- "An earlier pass thought..."
- "This turned out to be..."
- "This is real, not a mis-decode..."
- "The old page was wrong..."

Replace those with an address, bytes if useful, and the current interpretation.

## Final checklist

- The opening summary tells the reader what the page covers.
- Headings are sentence case and match `docs/SUMMARY.md` when applicable.
- Non-obvious claims carry `[confirmed]`, `[standard]`, or `[hypothesis]`.
- Addresses use `pp:addr`, `ram:addr`, `page_pp:addr`, or bare `0x....`
  intentionally.
- Official and inferred names follow `_CamelCase` and `snake_case`.
- External evidence is labeled by source.
- No prose narrates prior analyst mistakes.
- No banned padding words were introduced.
- `git diff --check` passes.
- The mdBook/Nix build passes, or the final response names why it could not run.
