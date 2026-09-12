(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GraphingDemoModel = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  const WIDTH = 96;
  const HEIGHT = 64;
  const SAMPLE_EDGE = 94;
  const Y_INTERVALS = 62;

  function checkedWindow(windowState) {
    const out = {
      xMin: Number(windowState.xMin),
      xMax: Number(windowState.xMax),
      yMin: Number(windowState.yMin),
      yMax: Number(windowState.yMax),
    };
    if (!Object.values(out).every(Number.isFinite)) throw new Error("Window values must be finite.");
    if (out.xMin >= out.xMax || out.yMin >= out.yMax) {
      throw new Error("Each window minimum must be smaller than its maximum.");
    }
    return out;
  }

  function roundHalfUp(value) {
    return value < 0 ? -Math.floor(-value + 0.5) : Math.floor(value + 0.5);
  }

  function realToGraphX(value, windowState) {
    const w = checkedWindow(windowState);
    return roundHalfUp((value - w.xMin) * SAMPLE_EDGE / (w.xMax - w.xMin));
  }

  function realToGraphY(value, windowState) {
    const w = checkedWindow(windowState);
    return roundHalfUp((value - w.yMin) * Y_INTERVALS / (w.yMax - w.yMin)) + 1;
  }

  function graphYToScreenRow(graphY) {
    return 63 - graphY;
  }

  function sampleColumnToReal(column, windowState) {
    const w = checkedWindow(windowState);
    return w.xMin + column * (w.xMax - w.xMin) / SAMPLE_EDGE;
  }

  function pixelToReal(x, y, windowState) {
    const w = checkedWindow(windowState);
    return {
      x: w.xMin + x * (w.xMax - w.xMin) / SAMPLE_EDGE,
      y: w.yMin + (62 - y) * (w.yMax - w.yMin) / Y_INTERVALS,
    };
  }

  function outCode(x, y) {
    return (x < 0 ? 1 : 0) | (x > 95 ? 2 : 0) | (y > 63 ? 4 : 0) | (y < 0 ? 8 : 0);
  }

  function clipLine(a, b) {
    let x0 = a.x, y0 = a.y, x1 = b.x, y1 = b.y;
    let c0 = outCode(x0, y0), c1 = outCode(x1, y1);
    for (let guard = 0; guard < 12; guard++) {
      if (!(c0 | c1)) return [{ x: roundHalfUp(x0), y: roundHalfUp(y0) }, { x: roundHalfUp(x1), y: roundHalfUp(y1) }];
      if (c0 & c1) return null;
      const code = c0 || c1;
      let x, y;
      if (code & 8) { x = x0 + (x1 - x0) * (0 - y0) / (y1 - y0); y = 0; }
      else if (code & 4) { x = x0 + (x1 - x0) * (63 - y0) / (y1 - y0); y = 63; }
      else if (code & 2) { y = y0 + (y1 - y0) * (95 - x0) / (x1 - x0); x = 95; }
      else { y = y0 + (y1 - y0) * (0 - x0) / (x1 - x0); x = 0; }
      if (code === c0) { x0 = x; y0 = y; c0 = outCode(x0, y0); }
      else { x1 = x; y1 = y; c1 = outCode(x1, y1); }
    }
    return null;
  }

  function rasterLine(a, b) {
    const clipped = clipLine(a, b);
    if (!clipped) return [];
    let x0 = clipped[0].x, y0 = clipped[0].y;
    const x1 = clipped[1].x, y1 = clipped[1].y;
    const dx = Math.abs(x1 - x0), sx = x0 < x1 ? 1 : -1;
    const dy = -Math.abs(y1 - y0), sy = y0 < y1 ? 1 : -1;
    let error = dx + dy;
    const pixels = [];
    while (true) {
      if (x0 >= 0 && x0 < WIDTH && y0 >= 0 && y0 < HEIGHT) pixels.push({ x: x0, y: y0 });
      if (x0 === x1 && y0 === y1) break;
      const twice = 2 * error;
      if (twice >= dy) { error += dy; x0 += sx; }
      if (twice <= dx) { error += dx; y0 += sy; }
    }
    return pixels;
  }

  function toScreenPoint(x, y, windowState) {
    return { x: realToGraphX(x, windowState), y: graphYToScreenRow(realToGraphY(y, windowState)) };
  }

  function evaluatePreset(preset, x) {
    if (preset === "square") return x * x;
    if (preset === "reciprocal") return x === 0 ? NaN : 1 / x;
    throw new Error("Unknown function preset.");
  }

  function functionScene(preset, windowState, xResolution) {
    const w = checkedWindow(windowState);
    const step = Math.max(1, Math.min(8, Math.trunc(Number(xResolution) || 1)));
    const events = [];
    const invalidColumns = [];
    let previous = null;
    let samples = 0, seeds = 0, connectors = 0, breaks = 0;
    for (let column = 0; column <= SAMPLE_EDGE; column += step) {
      const x = sampleColumnToReal(column, w);
      const y = evaluatePreset(preset, x);
      samples++;
      if (!Number.isFinite(y)) {
        invalidColumns.push(column);
        if (previous) breaks++;
        previous = null;
        continue;
      }
      const current = { realX: x, realY: y, column, ...toScreenPoint(x, y, w) };
      const from = previous || current;
      const kind = previous ? "connector" : "seed";
      if (previous) connectors++; else seeds++;
      events.push({ kind, from, to: current, pixels: rasterLine(from, current) });
      previous = current;
    }
    return { mode: preset, window: w, xResolution: step, events, samples, seeds, connectors, breaks, invalidColumns };
  }

  function circleScene(windowState, centerX, centerY, radius) {
    const w = checkedWindow(windowState);
    const cx = Number(centerX), cy = Number(centerY), r = Number(radius);
    if (![cx, cy, r].every(Number.isFinite) || r <= 0) throw new Error("Circle values must be finite and radius must be positive.");
    const events = [];
    for (let index = 0; index < 60; index++) {
      const a0 = index * Math.PI / 30;
      const a1 = (index + 1) * Math.PI / 30;
      const oldReal = { realX: cx + r * Math.cos(a0), realY: cy + r * Math.sin(a0) };
      const newReal = { realX: cx + r * Math.cos(a1), realY: cy + r * Math.sin(a1) };
      const from = { ...oldReal, ...toScreenPoint(oldReal.realX, oldReal.realY, w) };
      const to = { ...newReal, ...toScreenPoint(newReal.realX, newReal.realY, w) };
      events.push({ kind: "circle-segment", index, from, to, pixels: rasterLine(from, to) });
    }
    return { mode: "circle", window: w, centerX: cx, centerY: cy, radius: r, events, samples: 60, seeds: 0, connectors: 60, breaks: 0, invalidColumns: [] };
  }

  function axisPixels(windowState) {
    const w = checkedWindow(windowState);
    const pixels = [];
    if (w.yMin <= 0 && w.yMax >= 0) pixels.push(...rasterLine(toScreenPoint(w.xMin, 0, w), toScreenPoint(w.xMax, 0, w)));
    if (w.xMin <= 0 && w.xMax >= 0) pixels.push(...rasterLine(toScreenPoint(0, w.yMin, w), toScreenPoint(0, w.yMax, w)));
    return pixels;
  }

  function pixelsThrough(scene, eventCount) {
    const keys = new Set();
    for (const event of scene.events.slice(0, eventCount)) {
      for (const point of event.pixels) keys.add(point.x + "," + point.y);
    }
    return keys;
  }

  function packPlotScreen(pixelKeys) {
    const bytes = new Uint8Array(768);
    for (const key of pixelKeys) {
      const [x, y] = key.split(",").map(Number);
      if (x >= 0 && x < WIDTH && y >= 0 && y < HEIGHT) bytes[y * 12 + (x >> 3)] |= 0x80 >> (x & 7);
    }
    return bytes;
  }

  function createScene(options) {
    return options.mode === "circle"
      ? circleScene(options.window, options.centerX, options.centerY, options.radius)
      : functionScene(options.mode, options.window, options.xResolution);
  }

  return {
    WIDTH, HEIGHT, SAMPLE_EDGE, Y_INTERVALS, roundHalfUp,
    realToGraphX, realToGraphY, graphYToScreenRow, sampleColumnToReal,
    pixelToReal, rasterLine, functionScene, circleScene, axisPixels,
    pixelsThrough, packPlotScreen, createScene,
  };
});
