# MathPrint renderer + reverse-engineering

A standalone experimental model of TI-84 Plus OS 2.55MP MathPrint layouts. It
uses ROM-extracted font bitmaps and trace-fitted box geometry; it is not a
record interpreter or an emulator. Deployed beside the wiki at `/mathprint/`
(outside the mdBook). The reader-facing write-up is
[`docs/sub-equation-display.md`](../../docs/sub-equation-display.md).

## The page (this directory)

| File | Role |
|------|------|
| `index.html`, `style.css` | the interactive page |
| `app.js` | the renderer: glyph/box primitives → layout constructs → expression parser → canvas + draw-order animation + pen-log |
| `font.json` | large (`07:45FF`) + small (`03:4CD6`) font glyphs, extracted from ROM |
| `layout.json` | page-`0x39` class-table records and selected descriptors for inspection |

`app.js` is organized in sections: box primitives → layout constructs → text runs
→ expression parser → canvas rendering → UI. A "box" is `{rows, baseline, marks,
adv}`; `adv` (pen advance) is separate from the bitmap width so glyphs can
overhang. The marks are model-local composition metadata, not captured OS pen state.

## Tooling (in `tools/`)

| Tool | Purpose |
|------|---------|
| `export-font.py` | ROM → `font.json` (glyph data for the renderer and its font-table tab) |
| `export-layout.py` | ROM → `layout.json` (handler records, descriptors) |
| `interp-cells.js` | first-stage record-cell classifier for inspection |
| `trace_lcd.py` | replay reset-origin TilEm LCD I/O with its pinned T6A04 model |
| `parity-mathprint.py` | render an expression in TilEm and diff it against the model |
| `test-mathprint.js` | fuzz + corpus: every generated expression parses and lays out |
| `render-mathprint.py` | ASCII font/layout dump from ROM |

## Reverse-engineering specs (in `tools/`, decoded from raw disassembly)

- `cell-glyph-spec.md` — the `D:E` cell → glyph/token/marker dispatch (`39:4E8E`,
  `39:4F1A`, the `07:44DE` family tables).
- `token-name-spec.md` — ordinary cells → counted strings through `_KeyToString`
  (`01:6D10`, pointer table `01:6E05`).
- `geometry-spec.md` — placement math: `39:683D` cell→pixel, `39:6B1C` fraction
  endpoints, `39:5167`/`5949` row stepping, pen conversion.

## Verification status

`tools/test-mathprint.js` currently passes 5,018 deterministic parse/layout
smoke cases and checks rectangular boxes plus in-bounds composition marks. That
is robustness evidence, not calculator fidelity. `parity-mathprint.py` now uses
LCD trace replay when tracing is enabled, but the proprietary ROM and retained
MathPrint traces are unavailable in this checkout, so the historical
pixel-parity claims were not rerun and are not asserted here.

## Regenerate

```sh
python3 tools/export-font.py     # -> font.json
python3 tools/export-layout.py   # -> layout.json
node tools/test-mathprint.js     # fuzz
python3 tools/parity-mathprint.py  # calc-vs-model parity (needs TilEm + tools/rom.bin)
```
