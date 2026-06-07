---
name: ti84-re-review
description: Audit or correct TI-84 reverse-engineering claims against ROM bytes, Ghidra output, caller artifacts, emulator traces, and hardware evidence. Use for factual reviews of docs/*.md, bcall maps, routine semantics, RAM layouts, tokens, flags, ports, archive behavior, or community-program claims; pair with ti84-re-writing whenever Markdown changes.
---

# TI-84 RE accuracy review

Verify the specific claim, not merely the cited address. Keep ROM, source,
emulator, and physical-hardware evidence separate.

## Non-negotiable rules

- Read `ti84-re-writing` completely before editing Markdown.
- Inspect the worktree before acting. Preserve unrelated changes and stage only
  the intended files.
- Treat names, comments, readmes, decompiler output, and reviewer conclusions as
  leads. Confirm load-bearing semantics from primary artifacts.
- Do not call resolver additions “new bcalls” when the IDs already occupy
  aligned ROM-table entries. Separate ID-to-body mapping, name provenance, ABI,
  side effects, and runtime coverage.
- Do not promote emulator behavior to physical-hardware evidence.
- Do not run contributed host executables. Run calculator artifacts only in an
  isolated emulator when their provenance and scope are recorded.
- Leave unsafe or state-dependent routines unexecuted when an authentic caller
  state is unavailable. Document the exact missing state and mutation risk.

## Evidence model

Use each source for the question it can answer; do not force them into one
universal precedence order.

1. **Identity and provenance.** Identify the complete ROM, relevant page
   variants, include revision, tool revision, emulator binary, model, and OS.
   Read `docs/provenance.md` before using boot, certificate, USB, reset, or page
   `0x3F` evidence. Use `tools/rom_provenance.py` where applicable.
2. **ROM mapping.** Decode table entries and raw bytes. Verify that an address
   starts an instruction and that bank/page selection is correct. Use
   `tools/bcall_targets.txt`, `tools/ti83plus.inc`, `tools/ram.txt`, and the
   typed symbol files as distinct sources rather than interchangeable truth.
3. **Static control flow.** Use Ghidra listing, xrefs, and decompiler output;
   confirm ambiguous instructions from raw bytes or
   `nix develop -c z80dasm`. Prefer read-only headless scripts for repeatable
   bulk studies. Raw instruction decoding supersedes a misleading decompile.
4. **Caller evidence.** Distinguish a release binary, byte-identical rebuilt
   source, source-only control flow, readme claim, and third-party description.
   For community archives, record archive and member SHA-256 values.
5. **Runtime evidence.** Trace state-dependent behavior when practical. Pin the
   ROM, emulator, fixture, wrapper, macro, trace, and snapshot identities in a
   reduced CSV or JSON result.
6. **Physical evidence.** Require hardware measurements for ASIC aliasing,
   electrical behavior, timing margins, reset persistence, and other claims an
   emulator cannot establish.

Use `[confirmed]`, `[standard]`, and `[hypothesis]` as defined by
`ti84-re-writing`. Also state the evidence source locally: ROM control flow,
release source, TilEm trace, or physical probe.

## Review workflow

1. **Scope the slice.** Choose one mechanism or a small related set of claims.
   Read the target article and adjacent pages that repeat the same behavior.
2. **Inventory claims.** Extract routine names, bcall IDs, body addresses, RAM
   labels, table sizes, structure offsets, input state, outputs, cleanup, and
   error paths. Record which source is supposed to prove each claim.
3. **Check deterministic mappings first.** Compare index/table rows
   programmatically against the ROM and curated inputs. Add a regression test
   for exact row counts, names, targets, and provenance classes when the result
   is durable.
4. **Decode semantics.** Walk the complete routine and its relevant helpers.
   Check the caller as well as the callee. Verify operation direction, register
   lifetime, flag sense, pointer base, table stride, bounds, cleanup, and
   non-local error exits.
5. **Trace where behavior depends on state.** Prefer a shipped calculator
   artifact when its identity is known. Otherwise build the smallest safe
   caller that reconstructs an authentic ABI. Exercise interactive and error
   paths separately from nonblocking return paths.
6. **Reduce the trace.** Derive fixture call sites from assembled bytes, scope
   counts between a call anchor and a result/error marker, and validate the
   final RAM or ROM state. Do not treat global PC counts as fixture calls; OS
   loading and input may visit the same body. Supply the correct initial bank
   mapping, and reject unresolved mappings rather than guessing labels.
7. **Calibrate the result.** Use explicit classes such as `traced`,
   `partial-trace`, `return-traced`, `model-probed`, and `not-run`. State what
   remains static-only or hardware-only.
8. **Write narrowly.** Put behavior in the existing subsystem article unless
   it has an independent reference scope. Add packed C layouts when field
   widths and offsets are established. Reconcile sibling pages and remove
   duplicate catalogs.
9. **Commit by evidence slice.** Keep tooling, reduced runtime evidence, and
   documentation in focused commits when that improves reviewability. Do not
   commit large raw traces, temporary ROMs, extracted archives, or machine-local
   paths.

When subagents are requested or permitted, assign bounded independent slices:
mapping/provenance, static semantics, runtime replay, and writing consistency.
Require concrete addresses, hashes, commands, and evidence limits. The primary
agent must read the controlling skill, inspect the artifacts, reconcile
disagreements, and validate the combined result.

## Dynamic-trace discipline

- Read `tools/dynamic-tracing.md` before capturing TilEm traces.
- Capture all banked windows when page resolution matters.
- Use the reset mapping only when tracing begins at reset. A trace started after
  file transfer needs its actual initial selectors or a later proven mapping.
- Persist offsets or names across moving/GC-capable OS calls; reacquire VAT
  pointers after those calls.
- Verify observable state, not only body entry: registers, RAM records, port
  writes, Flash array contents, return markers, and handled errors as relevant.
- Rebuild fixtures byte-for-byte and replay reducers to byte-identical CSV/JSON
  output before committing.
- Record negative boundaries. A body not reached under one macro is evidence
  about that scenario, not proof that the routine is unreachable.

## Recurring failure checks

- bcall ID confused with body address or a table entry mistaken for an ABI
- little-endian operands reversed
- x/y, row/column, source/destination, archive/unarchive, or alloc/dealloc swap
- `SET`, `RES`, or `BIT` assigned to the wrong IY byte or bit
- caller behavior attributed to the callee
- address landing in data, a string, or the middle of an instruction
- table base, stride, bias, or inclusive range off by one
- propagating `LDIR` fill counted as `BC` rather than `BC + 1` bytes
- OP-register or two-byte-token labels copied from an incorrect comment
- bank-A pointer used while a bcall has remapped bank A
- success-path cleanup generalized to errors, reset, APD, or power loss
- community source treated as proof of the shipped binary or physical behavior

## Validation and handoff

- Run focused regression tests and every new analyzer under `nix develop`.
- Reassemble fixtures and compare their hashes with the accepted trace inputs.
- Run `git diff --check`, the wiki-style tests, mdBook/output-link checks, and
  `nix build` in proportion to the change.
- Classify unrelated failures by exact test and evidence identity; do not hide
  them or attribute them to the patch.
- Ensure docs, commit messages, and PR text contain no machine-local paths,
  reviewer lore, or claims broader than the evidence.
- Report changed files, focused commits, validations, and every remaining
  static-only, emulator-only, or hardware-only boundary.
