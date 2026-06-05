# Equation Display (MathPrint pretty-printer)

*TI-84 Plus OS 2.55MP — feature deep dive.*

How the OS lays a tokenized expression out as **2-D text** — the engine behind the homescreen entry line, the **Y= editor**, the **Solver** equation line, and the catalog/menu rendering. It is the single largest subsystem on **flash page 0x39** (≈147 functions, all prefixed `eqdisp_*`). This is the inverse of parsing: a token stream → pixels, with nesting, fraction bars, and indentation, rather than evaluation.

> Related: [Tokenizer & TI-BASIC](07-tokenizer-basic.md) (the token format it consumes), [Display & LCD](08-display-lcd.md) (the glyph blitter it drives), [Solver & Numerical Methods](sub-solver-numeric.md) (a consumer of the equation line).

## Where it sits

- A context (Y= editor, Solver, homescreen entry) needs to **show** the equation/expression the user is editing. It hands the token stream to the page-0x39 renderer.
- The renderer walks the tokens, classifies each, computes geometry (width/height/indent), and emits glyphs to the display via the page-1 font path (`_PutMap`/`_VPutMap`, see [Display & LCD](08-display-lcd.md)).
- Current token / current row state lives in RAM: `DAT_ram_85de` ≈ current token, `BYTE_ram_844b` ≈ current row (the same `curRow` the text display uses).

## Render loop [confirmed — from disassembly]

| Routine | Addr | Role |
|---------|------|------|
| `eqdisp_begin` | `39:49A8` | Entry: set up the render of an equation/expression. |
| `eqdisp_set_flag_render` | `39:4A02` | Mark "render mode" (vs measure-only geometry pass). |
| `eqdisp_render_entry` | `39:4A56` | The per-equation render driver. |
| `eqdisp_dispatch_token` | `39:4A74` | Read the current token and route it to a handler. |
| `eqdisp_classify_tok` | `39:4AEC` | Classify a token (operator / function / value / grouping). |
| `eqdisp_token_subdispatch` | `39:4B0E` | Secondary dispatch for multi-form tokens. |
| `eqdisp_load_tok_handler` | `39:4C27` | Load the handler for the classified token. |

The loop is the classic **measure-then-draw**: a geometry pass computes each sub-expression's bounding box, then a draw pass emits glyphs at the computed positions (so fractions, exponents, and nested parens align).

## Layout / geometry [confirmed]

| Routine | Addr | Role |
|---------|------|------|
| `eqdisp_layout_main` | `39:4F9A` | Top-level layout of the token stream. |
| `eqdisp_compute_dims` | `39:69C8` | Compute width/height of a (sub)expression. |
| `eqdisp_layout_token_geom` | `39:68AE` | Per-token geometry. |
| `eqdisp_setup_indent` | `39:4C40` | Indentation for nested/continued rows. |
| `eqdisp_sum_arg_widths` | `39:4DCA` | Sum argument widths (for multi-arg functions). |
| `eqdisp_layout_arg` / `eqdisp_layout_multiarg` | `39:513E` / `39:5167` | Lay out one / several arguments. |
| `eqdisp_emit_subexpr` / `_2` | `39:4C5A` / `39:4CA4` | Recurse into a sub-expression. |
| `eqdisp_set_row_for_tok` | `39:4CE9` | Choose the output row for a token. |

## Glyph emission [confirmed]

| Routine | Addr | Role |
|---------|------|------|
| `eqdisp_emit_glyph` | `39:4E8E` | Emit one glyph at the current pen position. |
| `eqdisp_map_token_glyph` | `39:4F1A` | Map a token to its glyph(s). |
| `eqdisp_emit_digit` / `_chk` | `39:4E14` / `39:4E0A` | Emit a numeric digit. |
| `eqdisp_glyph_width` | `39:6BE7` | Width of a glyph (for proportional layout). |
| `eqdisp_load_glyph18b` / `_2` | `39:6B62` / `39:6B66` | Load an 18-byte (large/2-row) glyph. |
| `eqdisp_draw_fraction_bar` | `39:6ABF` | Draw the horizontal fraction bar. |
| `eqdisp_advance_col6` | `39:6B1C` | Advance the pen column by 6 px. |
| `gr_draw_tbl_glyph` | `39:66DC` | Draw a glyph from a table. |

## Cursor & bounds [confirmed]

The editor needs to know where the **cursor** falls within the 2-D layout and whether the expression overflows the screen:

- `eqdisp_cmp_cursor_bounds` (`39:4F44`) — is the cursor inside the visible region?
- `eqdisp_set_overflow_jp` (`39:6712`) / `eqdisp_chk_state_e5` (`39:671D`) — overflow / scroll state.
- `eqdisp_save_disp_state` / `eqdisp_restore_disp_state` (`39:57CF` / `39:5801`) and the `_e7`/`_f2` OP-save helpers (`39:5ABC`+) — save/restore display + OP-register state across the recursive layout (so the renderer doesn't clobber the caller's math registers).

## Menus

The same page hosts menu rendering used by editors:

- `mnu_show_and_getkey` (`39:5466`) — draw a menu and wait for a key.
- `mnu_restore_app_state` (`39:6D96`) / `mnu_clear_flag` (`39:6DD5`) — restore after a menu.
- `eqdisp_menu_dispatch` (`39:545B`) / `eqdisp_menu_or_emit` (`39:53AD`) — menu vs glyph branch.

## Takeaway

Page 0x39 is a self-contained **2-D expression typesetter**: a recursive measure→draw walk over the token stream that classifies each token, computes its bounding box (handling fractions, arguments, nesting, indentation), and emits proportional glyphs through the font path — while preserving the caller's OP registers and tracking the cursor for in-place editing. It is invoked by every context that shows an editable equation.

## TODO
- Map the exact token→layout-class table (`eqdisp_classify_tok` lookup) and the fraction/exponent stacking rules.
- Trace how the Y= editor / Solver hand their token stream in (entry args to `eqdisp_begin`).
- Confirm the MathPrint vs Classic mode switch (if present on 2.55MP).
