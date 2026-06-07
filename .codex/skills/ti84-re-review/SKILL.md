---
name: ti84-re-review
description: Accuracy-audit a TI-84 reverse-engineering wiki page against ROM ground truth. Use when verifying or correcting factual claims in docs/*.md — routine addresses, bcall IDs, RAM labels, token/type/error values, flag bits, byte-level semantics, control flow, or any "the ROM does X" assertion. Pairs with ti84-re-writing (notation/prose); this skill is about *correctness*, not style.
---

# TI-84 RE accuracy review

Use this skill to check that every factual claim in a `docs/*.md` page matches
the ROM. It encodes the ground-truth precedence, the reviewer-reliability model,
the recurring error patterns, and the per-article workflow that an audit pass of
the whole wiki converged on.

The cardinal rule: **a reviewer (including a Claude subagent) can be wrong.
Byte-verify every load-bearing claim yourself before you write or accept it.**
Reviewers confirmed false claims and flagged true ones in roughly equal measure;
the bytes are the only authority.

## 1. Ground truth, in strict precedence

Escalate tiers only on ambiguity; record which tier settled each check.

1. **Ghidra MCP bridge** at `http://127.0.0.1:8080` (curl):
   `searchFunctions?query=`, POST bare name to `/decompile` (header line
   `bcall(_Name) id=0xXXXX [NN:ADDR]`), `disassemble_function?address=0x..`,
   `get_function_by_address`, `xrefs_to`/`xrefs_from`, `segments`. Ground truth
   is the **instruction that STARTS at the address** and what it does — not a
   name match (names were partly seeded from a WikiTI-lineage `.inc`, so a name
   only corroborates). The bridge resolves page 0 as `ram:addr`.
2. **Raw bytes** of `tools/rom.bin`: flash page `NN` is at file offset
   `NN*0x4000 + (addr - 0x4000)`; page 0 (`addr < 0x4000`) is at file offset
   `= addr`. Decode with python/`xxd`. Companion tables: `tools/ti83plus.inc`
   (equates, tokens, errors, flag bits), `tools/ram.txt` (RAM labels),
   `tools/bcall_targets.txt` (`NAME ID BODYADDR PAGE`), `tools/names.txt`
   (inferred/auto names), `tools/ports.txt`, `docs/token-tables.md`,
   `tools/ty_error.txt`/`ty_vartype.txt`/`ty_token.txt`.
3. **z80dasm** (`/opt/homebrew/bin/z80dasm`) on a carved page when Ghidra is
   ambiguous. It needs a writable temp dir; if sandboxed, decode bytes directly.
4. **Headless TilEm** (`tools/dynamic-tracing.md`) only when static cannot decide.

**The two-image model (critical).** `tools/rom.bin` is a *BootFree* dump: page
`2F` is all-`0xFF` (blank) and page `3F` is a non-blank **substitute** boot page
(`3F:4000 = 3E 3F D3 06 D3 07 C3 2C 81`). The **retail** boot/cert/USB pages live
in `D84PBE1.8Xv` (page 3F) and `D84PBE2.8Xv` (page 2F) — each is a `74`-byte
header + 16384-byte page + 2-byte trailing checksum, so logical `0xADDR` is at
file offset `74 + (ADDR - 0x4000)` (NOT 76 — `len - 16384 = 76` counts the
checksum). `ti84plus_patched.rom` is the full retail image (page `NN` at physical
`NN*0x4000`, no header) and is the cleanest source for any `3F:`/`2F:` body. So
"page 3F is blank in rom.bin" is wrong; distinguish *blank* from *substitute*
from *retail*.

## 2. Reviewer reliability — who to trust for what

- **Claude subagent verifier** — good at confirming an address *exists* and
  decodes to *some* plausible instruction, and at breadth (coverage of every
  cited routine/label). It **rubber-stamps semantics**: direction (read vs
  write), axis (x vs y), which register/flag/bit, operand order, set vs clear,
  index/bias arithmetic. It declared whole pages "0 wrong / exact" that had
  real x/y swaps and reversed-direction claims. Use it for coverage, and *always
  instruct it* to mark any direction/semantic/flag/index claim as
  `NEEDS-BYTE-CHECK` with the bytes it decoded, rather than "CONFIRMED".
- **psi** (`tools/audit/psi-review.sh`) and **codex**
  (`tools/audit/codex-review.sh`) — the semantic gate; an independent model
  (gpt-5.5) on the repo OAuth credential. They caught the errors Claude missed
  (the archive/unarchive worker swap, the sub-graphing `_IOffset`/`_HorizCmd`
  semantics, `_GetTokLen`, the `_GetKey` alpha one-shot). They **hang
  intermittently** (~half the runs: MCP-retry stall, 0 output → the 900s
  timeout). When that happens, `pkill -f "review.sh docs/<name>"` and relaunch;
  they usually work on a retry. They cannot reach the bridge from their sandbox,
  so they work from raw bytes + the repo tables.
- **The scan** (`tools/audit/scan_names_addrs.py docs/X.md`) — cheap first pass
  for fabricated `_CamelCase` names, address mismatches, and slash-compressed
  forms. Advisory; confirm each with a reviewer.

Lead with psi/codex + your own byte-decode for semantics; use Claude for breadth.
See the persisted memory `audit-reviewer-reliability` for the same finding.

**Verify the verifier.** Reviewers (Claude *and* psi/codex) made these mistakes
during the audit — re-derive their claims:
- Miscounting a **propagating-LDIR memset** (`LD (HL),0; LD DE,HL+1; LDIR BC`)
  as `BC` bytes when it zeroes `BC+1` (start..`start+BC` inclusive). The doc was
  right; the reviewer was off by one. Do not "fix" these down by one.
- Using the wrong `.8Xv` header size (`74` vs `76`), shifting a retail decode by
  2 bytes (it claimed `3F:412C` starts with `IM 1` when `IM 1` is at `412A`).
- Confusing a **bcall ID with a body address** (looked for `CALL 43A2` when the
  routine `CALL`s the body `152A`).
- Reading the byte **before** a `CALL` (claimed the dispatch was at `0112` when
  `cd 93 3f` starts at `0113`).

## 3. Recurring error classes to hunt

These are the bug families the audit actually found. Check each explicitly:

- **x/y (axis) swaps** — which coordinate drives the LCD page/row vs column
  command; which of `H`/`L` is stored to `penCol`(x)/`penRow`(y) or `curRow`/
  `curCol`. (`_IOffset`, `683D` both had this.)
- **Little-endian operand misreads** — `ED 5B xx yy` = `LD DE,(yyxx)`;
  `21 xx yy` = `LD HL,yyxx`. The prose may transpose the two bytes (`(065B)` for
  `(9306)`; `(D35B)` for `(84D3)`).
- **bcall ID vs body address** — `0x50DD` is an *ID*; the body is `07:7345`. Never
  print an ID as a `00:addr`. (Format: `_Name (pp:body, id 0xNNNN)`.)
- **Address landing in DATA** — decode and check ASCII / table shape; `00:4105`
  was a `"Resetting All…"` string, not the `reTable` setter.
- **Operation direction** — archive vs unarchive (RAM var `B==0` → archive;
  Flash var `B≠0` → unarchive), alloc vs dealloc (`_DeallocFPS1 = JP/CALL 152A`
  shrinks `FPS`), read-window-into-frame vs write-window, set vs clear a flag.
- **OP-register labels** — `OP1=8478, OP2=8483, OP3=848E, OP4=8499, OP5=84A4,
  OP6=84AF`. `8483`≠OP3, `8499`≠OP6. `(OP1+1)=0x8479` is the exp byte for a float
  but the type/name byte when OP1 holds a name.
- **Token prefix** — 2-byte tokens are `t2ByteTok` (`0xBB`)-prefixed; the lead
  bytes are exactly `5C 5D 5E 60 61 62 63 7E AA BB EF` (table at `ram:1FF6`,
  `_IsA2ByteTok ram:1FE8`). `0xE1` is a keycode, not a token lead byte.
- **Flag byte/bit attribution** — `(IY+3)` is `graphFlags.graphDraw` (inc:
  `graphFlags=3`/`graphDraw=0`), not `grfDBFlags`(=4) nor SmartGraph(`IY+0x17`).
  `(IY+0x35)` is `hookflags3`. Confirm `SET n` vs `SET m` and `BIT 6` vs `BIT 4`
  against `fd cb dd op` (`46/4E/56...`=BIT 0/1/2; `C6/CE...`=SET; `86/8E...`=RES).
- **Index/bias arithmetic** — verify table base, stride (`×2` for word ptrs),
  and any `+0x28`/`+0x29`/`-0x20` class bias by decoding the table and the
  add/`SUB` instructions.
- **Attribution to the wrong routine** — a `+0x12` fold or a flag op may live in
  the *caller*, not the named callee. Trace the actual call site.
- **Off-by-N instruction addresses** — cite the address where the instruction
  *starts*; the doc often points at the surrounding micro-sequence.
- **Raw Ghidra auto-names** (`FUN_ram_*`, `SUB_*`, `UNK_*`, `p07_ret_a`) left in
  prose — replace with bare `ram:addr`/`pp:addr` or an inferred snake_case name;
  if a `names.txt` auto-name is meaningless or contradicts behavior, say the name
  is inferred rather than asserting it is "the live DB name".

## 4. Per-article workflow (what converged)

1. **Scan**: `python3 tools/audit/scan_names_addrs.py docs/X.md`.
2. **Fan out in parallel**: a Claude breadth verifier (it reads the doc itself —
   saves your context; instruct it to flag semantics as `NEEDS-BYTE-CHECK`) +
   `psi-review.sh` + `codex-review.sh` (background; `CODEX_REVIEW_TIMEOUT=900`).
3. **Reconcile**: collect all findings. **Byte-verify every substantive/semantic
   finding yourself** (point 2's "verify the verifier"). Reject reviewer
   false-positives with byte evidence; accept and fix the real ones.
4. **Fix narrowly**, preserving claims the bytes support. Cross-doc: a finding
   often applies to sibling pages that cite the same address (the arc swap hit
   `12-memory-management` too) — fix those in the same pass.
5. **Converge**: re-run a round until reviewers report nothing new (or only
   notation / already-rejected). When psi/codex hang, a thorough Claude breadth
   pass + your byte-decoding is sufficient; relaunch psi/codex as a post-commit
   cross-check.
6. **Commit per article**, with byte evidence in the message (addresses, the
   decoded instruction, the inc line). Follow `ti84-re-writing`: no "review" /
   "audit" meta-language in committed markdown, page-0 code uses `ram:`, flash
   uses `pp:addr`, bcall ID ≠ body, prefer `[confirmed]/[standard]/[hypothesis]`.

## 5. Efficiency

- **Index docs** (`bcall-index.md`, `token-tables.md`): cross-check
  *programmatically*, not with a subagent. Regex the `| _Name | id | pp:addr |`
  rows and diff against `tools/bcall_targets.txt` (all rows matched exactly in
  the audit); cross-check `token-tables` lead bytes + count against `07` and the
  inc. The `0x8xxx` boot rows aren't in `bcall_targets` — check them against the
  retail boot-table values (`_WriteAByte 8021→3F:4C9F`, `_InitUSB 8108→2F:52A4`).
- **Overview/meta docs** (`00`, `99`): the claims cross-reference audited pages;
  spot-check only the few unique anchors (`reset ram:0000`, `bcall_dispatcher
  ram:2a2f` via `JP` at `0x0028`, `int_dispatch_sources ram:006f`).
- **Don't block on hung reviewers.** Kill and relaunch; keep moving with Claude
  breadth + byte-decode; fold a late psi/codex result as a follow-up if it lands.
- **Keep the audit tooling out of git** (`tools/audit/` is gitignored: the
  `.codex-home`/`.psi-home` credentials, `STATUS.md`, `findings/`, `PROTOCOL.md`).
- Watch for a recurring stray clobber of `tools/bcalls8x_targets.txt`
  (truncated to 2 lines) — `git checkout --` it before committing.

## 6. Confidence calibration

- `[confirmed]` only when you decoded the bytes (or the bridge decompiled the
  body) and they say what the prose says — *for the specific semantic claim*, not
  just that an address exists.
- A reviewer's "CONFIRMED" on a direction/axis/register/flag claim is **not**
  sufficient; downgrade it to your own byte check.
- Behavioral claims (numeric results, screen output, externally-sourced names
  like the TI link-protocol guide or TI-Toolkit tokens) are `[standard]` unless
  byte-traced; mark them so rather than `[confirmed]`.
