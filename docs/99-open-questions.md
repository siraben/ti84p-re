# 99 — Open questions & future work

The structural reverse-engineering is comprehensive (every subsystem mapped, both cross-page mechanisms resolved, full input→parse→eval→display pipeline documented). What remains is **depth**, gathered here from the per-doc TODOs and prioritized. Each is self-contained for a future session.

## Resolved

1. **Flash sector write/erase primitive map** — live MCP confirms anchors such as `flash_program_buf`@`3D:678C`, `flash_erase_wait`@`3D:5ED3`, `flash_cmd_base`@`3D:738B`, and `flash_op_fd/fb/fe`@`3D:7C8F/7C93/7C97`; older labels at `3D:61AF`, `3D:64AA`, `3D:62C2`, `3D:6413`, and `3D:6B9B` need a fresh symbol pass. See [sub-vat-archive.md](sub-vat-archive.md) / [12](12-memory-management.md).
2. **Flash archive garbage collector** — the behavior is documented, but older labels `flash_gc_relocate`@`3C:7BD0`, `gc_show_screen`@`3C:7E0D`, and `flash_cmd_dispatch`@`3C:7121` are not current live-MCP functions. Re-map the GC path from the live DB before treating those addresses as confirmed.
3. ~~**VAT entry binary layout**~~ ✅ **DONE** — field order/size per object class documented from `_FindSym`'s scan (`findsym_scan`@`07:565F`) and the create-header writes. See [05](05-variables-vat.md).
4. ~~**Parser precedence levels**~~ ✅ **DONE** — the recursive-descent productions and the sub-dispatch tables at `page_38:5110`/`5127` are mapped via `parse_eval_expr`@`38:5AB3`. See [07](07-tokenizer-basic.md).
5. ~~**Event/context `0x3f3f` router**~~ ✅ **DONE** — resolved to the RAM-resident vector reaching `event_key_router`@`page_07:4539`; the 8-slot context stack near `0x84BE` is documented. See [11](11-boot-contexts-errors.md).
6. **84+-era bcalls / page 0x3F reconciliation** — historical scripts decoded 11 `0x8xxx` candidates from a page-0x3F table and cataloged them in `ti84plus_extra.inc`, but the current live Ghidra/MCP DB does not expose functions at those claimed targets. Reconcile the loader/build artifacts before treating them as confirmed bcalls; see [03](03-bcall-mechanism.md).
7. ~~**Equation display core (page 0x39)**~~ ✅ **DONE** — page 0x39's classification, handler records, descriptor templates, recursive operand walker, and glyph/string output paths are documented as a cell-grid typesetter. See [sub-equation-display.md](sub-equation-display.md).
8. ~~**Name every `FUN_` helper**~~ ✅ **DONE** — 100% of the 2413 functions are now named (`tools/names.txt` + `RenameFns.java`).
9. ~~**Font glyph page**~~ ✅ **DONE** — the large-font glyph table is on **page 0x07 at base `0x45FF`** with a **7-byte stride** (`put_glyph_large` `07:4588` → `lgfont_glyph_ptr_adjust` `07:45EB`); alternate fonts on pages 1/0x36. See [08](08-display-lcd.md), [13](13-flash-page-map.md).
10. ~~**Token→layout-class table**~~ ✅ **DONE** — `eqdisp_load_tok_handler` (`39:4C27`) indexes the 0x44-entry table at `0x5E45` by class byte; fraction/superscript forms are selected by a `+0x28`/`+0x29` class bias. See [sub-equation-display.md](sub-equation-display.md).
11. ~~**FP transcendental coefficient tables**~~ ✅ **DONE** — `ram:2362` was resolved as a bcall entry to `page_02:7D1E`, not a page selector. The ln/e^x/sin-cos coefficient tables and loop bounds are byte-dumped in [06](06-floating-point.md): ln/e^x use the 16-row `02:7181` table; sin/cos uses the signed 8-row `02:7201`/`02:7281` tables.
12. ~~**MathPrint tall-template composition**~~ ✅ **DONE** — `eqdisp_layout_multiarg` (`39:5167`) is the row compositor for multi-argument/tall templates; fixed glyph cells still emit through `39:4E8E`/`39:4F1A`, and rule-like UI surfaces use the rectangle helpers. See [sub-equation-display.md](sub-equation-display.md).

## Still open

13. **Enum equates.** Apply `TIKeyCode`/`TIError`/`TIVarType` to scalar operands in the relevant handlers (conservative, scoped).
14. **Smaller residuals** (in each doc's local TODO): absolute APD timeout/blink period (page-0x35 crystal-timer handler is unanalyzed data), the For/While/Repeat FPS loop-frame byte layout (page-0x33 dispatch confirmed), and the group-archive member walk (`_Arc_Unarc`'s `CP 0x17` reject routes elsewhere; body fragmented by cross-page calls).

## How to continue
Reopen `~/Documents/ti84-re/ti84.gpr` (the GhidraMCP plugin reconnects for interactive work), or extend the headless pipeline in `tools/` and rebuild with `tools/build.sh`. The remaining items mostly need a **headless raw-byte dump** of regions the live decompiler leaves as unanalyzed data (the page-0x35 timer handler, the page-0x38 `0xBB`/class-3 dispatch tables).
