# 99 — Open Questions & Future Work

The structural reverse-engineering is comprehensive (every subsystem mapped, both cross-page mechanisms resolved, full input→parse→eval→display pipeline documented). What remains is **depth**, gathered here from the per-doc TODOs and prioritized. Each is self-contained for a future session.

## High value

1. **Flash sector write/erase primitives** (`12`). RAM-resident (84+-specific, not in the 2001 `.inc`), write via flash-control port `0x14`. *Approach:* trace `_Arc_Unarc`'s data-move path on page 7 to the RAM stub the boot copies in; find the sector-erase command sequence. Security-relevant.
2. **Flash archive garbage collector** (`12`). The real "Garbage Collecting…" routine (distinct from `cleanup_temp_ram`). *Approach:* the message string isn't directly xref'd (indexed string display) — find the string-table index display routine, or trace from `_Arc_Unarc` when the archive is full.
3. **VAT entry binary layout** (`05`). Exact field order/size per object class. *Approach:* trace `_FindSym`'s scan loop (it tail-calls `cross_page_jump` to a body on another page) and `_CreateProg`/`_CreateAppVar` header writes.
4. **Parser precedence levels** (`07`). Map the recursive-descent productions (term/factor/unary) and the sub-dispatch tables at `page_38:5110`/`5127`. *Approach:* trace `parse_eval_expr` (`38:5AB3`) recursion and the `code *` handler pointers.

## Medium value

5. **Event/context stack semantics** (`11`). The 8-slot stack near `0x84BE` and the `0x3f3f` router in `main_event_loop`. *Approach:* `0x3f3f` is a RAM-resident routine vector — resolve its bjump target and trace.
6. **Font glyph page** (`08`,`13`). The large-font 8-byte glyph table — `_PutMap` reaches its blitter via trampoline `0x3B3D → page_07:4588`; find where that reads the glyph bytes (a page in `08–32`).
7. **FP transcendental coefficients** (`06`). Map the page-7 minimax/CORDIC coefficient tables to `_SinCosRad`/`_LnX`/`_EToX` and document the polynomial-eval method.
8. **84+-era bcalls** (`03`). ~88 `0x8xxx` bcall IDs show unnamed (the 2001 `.inc` predates them). A newer TI-84+ `.inc`/symbol file would close this.

## Low value / mechanical

9. **Name the ~980 remaining `FUN_` helpers.** Most aren't confidently namable from decompilation alone; best done opportunistically while pursuing 1–8. Use `tools/names.txt` + `RenameFns.java` to accumulate.
10. **Enum equates.** Apply `TIKeyCode`/`TIError`/`TIVarType` to scalar operands in the relevant handlers (conservative, scoped).

## How to continue
Reopen `~/Documents/ti84-re/ti84.gpr` (the GhidraMCP plugin reconnects for interactive work), or extend the headless pipeline in `tools/` and rebuild with `tools/build.sh`. Pick an item above and trace from the named anchor it gives.
