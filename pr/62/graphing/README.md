# Graphing pipeline demo

A standalone interactive visualization of the TI-84 Plus OS 2.55MP graphing
paths documented in [`docs/sub-graphing.md`](../../docs/sub-graphing.md). The
page is deployed beside the wiki at `/graphing/`, outside mdBook.

`model.js` contains the dependency-free coordinate, clipping, Bresenham,
function-sampling, Circle-segment, and `plotSScreen` packing model. `app.js`
connects that model to the controls and canvas in `index.html`.

The page deliberately separates verified structure from browser arithmetic.
Its 96×64 buffer geometry, 0–94 sample columns, 1-based bottom-up Y coordinate,
discontinuity break, and 60-segment Circle schedule follow the ROM and retained
traces. JavaScript numbers replace the calculator's packed-BCD engine.
