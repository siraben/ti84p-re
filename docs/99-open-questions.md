# 99 — Open Questions & Future Work

The structural reverse-engineering is comprehensive (every subsystem mapped, both cross-page mechanisms resolved, full input→parse→eval→display pipeline documented). What remains is **depth**, gathered here from the per-doc TODOs and prioritized. Each is self-contained for a future session.

## Resolved (subagent RE pass)

1. ~~Flash sector write/erase primitives~~ ✅ **DONE** — `flash_program_core`@`3D:61AF` (port `0x14`), `flash_write_byte`@`3D:6B9B`, `flash_alloc_sector`@`3D:62C2`. See `sub-vat-archive.md` / `12`.
2. ~~Flash archive garbage collector~~ ✅ **DONE** — `flash_gc_relocate`@`3C:7BD0` + `gc_show_screen`@`3C:7E0D` + dispatch `flash_cmd_dispatch`@`3C:7121`. See `sub-vat-archive.md`.

## Still open — high value
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
