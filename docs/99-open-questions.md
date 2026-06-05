# 99 — Open Questions & Future Work

The structural reverse-engineering is comprehensive (every subsystem mapped, both cross-page mechanisms resolved, full input→parse→eval→display pipeline documented). What remains is **depth**, gathered here from the per-doc TODOs and prioritized. Each is self-contained for a future session.

## Resolved (subagent RE pass)

1. ~~Flash sector write/erase primitives~~ ✅ **DONE** — `flash_program_core`@`3D:61AF` (port `0x14`), `flash_write_byte`@`3D:6B9B`, `flash_alloc_sector`@`3D:62C2`. See [sub-vat-archive.md](sub-vat-archive.md) / [12](12-memory-management.md).
2. ~~Flash archive garbage collector~~ ✅ **DONE** — `flash_gc_relocate`@`3C:7BD0` + `gc_show_screen`@`3C:7E0D` + dispatch `flash_cmd_dispatch`@`3C:7121`. See [sub-vat-archive.md](sub-vat-archive.md).
3. ~~**VAT entry binary layout**~~ ✅ **DONE** — field order/size per object class documented from `_FindSym`'s scan (`findsym_scan`@`07:565F`) and the create-header writes. See [05](05-variables-vat.md).
4. ~~**Parser precedence levels**~~ ✅ **DONE** — the recursive-descent productions and the sub-dispatch tables at `page_38:5110`/`5127` are mapped via `parse_eval_expr`@`38:5AB3`. See [07](07-tokenizer-basic.md).
5. ~~**Event/context `0x3f3f` router**~~ ✅ **DONE** — resolved to the RAM-resident vector reaching `event_key_router`@`page_07:4539`; the 8-slot context stack near `0x84BE` is documented. See [11](11-boot-contexts-errors.md).
6. ~~**84+-era bcalls**~~ ✅ **DONE** — the `0x8xxx` bcalls dispatch through a **second jump table on flash page 0x3F** (boot page), indexed by `ID & 0x7FFF`. Resolved + cataloged in `ti84plus_extra.inc`; see [03](03-bcall-mechanism.md).
7. ~~**Equation pretty-printer (page 0x39)**~~ ✅ **DONE** — the ~147 `eqdisp_*` functions are documented as a 2-D measure→draw typesetter. See [sub-equation-display.md](sub-equation-display.md).
8. ~~**Name every `FUN_` helper**~~ ✅ **DONE** — 100% of the 2413 functions are now named (`tools/names.txt` + `RenameFns.java`).

## Still open — high value

9. **Font glyph page** ([08](08-display-lcd.md), [13](13-flash-page-map.md)). The large-font 8-byte glyph table — `_PutMap` reaches its blitter via trampoline `0x3B3D → page_07:4588`; find where that reads the glyph bytes (a page in `08–32`). *Partial:* the blitter path is traced; the raw glyph table page is not yet pinned.
10. **FP transcendental coefficients** ([06](06-floating-point.md)). Map the page-7 minimax/CORDIC coefficient tables to `_SinCosRad`/`_LnX`/`_EToX` and document the polynomial-eval method.

## Medium value

11. **Token→layout-class table** ([sub-equation-display.md](sub-equation-display.md)). The `eqdisp_classify_tok` lookup and the fraction/exponent stacking rules.
12. **Enum equates.** Apply `TIKeyCode`/`TIError`/`TIVarType` to scalar operands in the relevant handlers (conservative, scoped).

## How to continue
Reopen `~/Documents/ti84-re/ti84.gpr` (the GhidraMCP plugin reconnects for interactive work), or extend the headless pipeline in `tools/` and rebuild with `tools/build.sh`. Pick an item above and trace from the named anchor it gives.
