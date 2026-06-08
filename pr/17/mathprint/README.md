# MathPrint renderer + reverse-engineering

A standalone, ROM-grounded reconstruction of the TI-84 Plus OS 2.55MP MathPrint
2-D layout engine (flash page `0x39`). Deployed beside the wiki at `/mathprint/`
(outside the mdBook). The reader-facing write-up is
[`docs/sub-equation-display.md`](../../docs/sub-equation-display.md).

## The page (this directory)

| File | Role |
|------|------|
| `index.html`, `style.css` | the interactive page |
| `app.js` | the renderer: glyph/box primitives → layout constructs → expression parser → canvas + draw-order animation + pen-log |
| `font.json` | large (`07:45FF`) + small (`03:4CD6`) font glyphs, extracted from ROM |
| `layout.json` | the page-`0x39` class table + every handler record + descriptors |

`app.js` is organized in sections: box primitives → layout constructs → text runs
→ expression parser → canvas rendering → UI. A "box" is `{rows, baseline, marks,
adv}`; `adv` (pen advance) is separate from the bitmap width so glyphs can
overhang, mirroring the OS pen pipeline.

## Tooling (in `tools/`)

| Tool | Purpose |
|------|---------|
| `export-font.py` | ROM → `font.json` + `docs/font-table.md` |
| `export-layout.py` | ROM → `layout.json` (handler records, descriptors) |
| `interp-cells.js` | resolve a record's cells to glyph/token/marker (data-driven) |
| `trace_lcd.py` | reconstruct the exact LCD from a trace's `OUT 0x10/0x11` stream (T6A04) |
| `parity-mathprint.py` | render an expression on the calc, diff vs the model (exact trace ref via `trace_lcd`) |
| `test-mathprint.js` | fuzz + corpus: every generated expression parses and lays out |
| `render-mathprint.py` | ASCII font/layout dump from ROM |

## Reverse-engineering specs (in `tools/`, decoded from raw disassembly)

- `cell-glyph-spec.md` — the `D:E` cell → glyph/token/marker dispatch (`39:4E8E`,
  `39:4F1A`, the `07:44DE` family tables).
- `token-name-spec.md` — token cells → drawn strings via the standard OS drawer
  (`01:6702`, table `01:4252`, `07:4000` remap).
- `geometry-spec.md` — placement math: `39:683D` cell→pixel, `39:6B1C` fraction
  endpoints, `39:5167`/`5949` row stepping, pen conversion.

## Fidelity

Against the exact trace→LCD reference, the inline constructs are pixel-perfect:
text, exponents (`X^2`), linear `1/2`, stacked fractions (`1//2`), and radicals
(`sqrt(...)`). The tall operators (`int`, `sum`, nth root) match in operator
sign, limits, and overall dimensions; their body's internal glyph advances come
from a RAM-relocated bcall (`0xC951`) whose width table is not in flash, so those
few pixels are trace-pinned rather than ROM-derivable.

## Regenerate

```sh
python3 tools/export-font.py     # -> font.json + docs/font-table.md
python3 tools/export-layout.py   # -> layout.json
node tools/test-mathprint.js     # fuzz
python3 tools/parity-mathprint.py  # calc-vs-model parity (needs TilEm + tools/rom.bin)
```
