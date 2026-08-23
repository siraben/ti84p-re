"use strict";

const assert = require("assert");
const M = require("../web/graphing/model.js");

const windowState = { xMin: -10, xMax: 10, yMin: -10, yMax: 10 };
assert.strictEqual(M.realToGraphX(-10, windowState), 0);
assert.strictEqual(M.realToGraphX(0, windowState), 47);
assert.strictEqual(M.realToGraphX(10, windowState), 94);
assert.strictEqual(M.realToGraphY(-10, windowState), 1);
assert.strictEqual(M.realToGraphY(0, windowState), 32);
assert.strictEqual(M.realToGraphY(10, windowState), 63);
assert.strictEqual(M.realToGraphY(8.872793118, windowState), 60);
assert.strictEqual(M.graphYToScreenRow(60), 3);

const square = M.functionScene("square", windowState, 1);
assert.strictEqual(square.samples, 95);
assert.strictEqual(square.invalidColumns.length, 0);
assert.strictEqual(square.breaks, 0);

const reciprocal = M.functionScene("reciprocal", windowState, 1);
assert.deepStrictEqual(reciprocal.invalidColumns, [47]);
assert.strictEqual(reciprocal.breaks, 1);
assert.strictEqual(reciprocal.seeds, 2);
assert.strictEqual(reciprocal.connectors, 92);
assert.strictEqual(reciprocal.events.length, 94);
assert.ok(!reciprocal.events.some(event => event.from.column < 47 && event.to.column > 47));

const circle = M.circleScene(windowState, 0, 0, 5);
assert.strictEqual(circle.events.length, 60);
assert.strictEqual(circle.events[0].from.realX, 5);
assert.ok(Math.abs(circle.events[0].to.realX - 4.9726094768414) < 1e-12);
assert.ok(Math.abs(circle.events[0].to.realY - 0.52264231633825) < 1e-12);
for (let index = 1; index < circle.events.length; index++) {
  assert.strictEqual(circle.events[index - 1].to.realX, circle.events[index].from.realX);
  assert.strictEqual(circle.events[index - 1].to.realY, circle.events[index].from.realY);
}

const pixels = M.pixelsThrough(circle, circle.events.length);
const packed = M.packPlotScreen(pixels);
assert.strictEqual(packed.length, 768);
assert.ok(pixels.size > 0);
assert.strictEqual([...packed].reduce((sum, value) => sum + value.toString(2).replace(/0/g, "").length, 0), pixels.size);

assert.throws(() => M.createScene({ mode: "square", window: { ...windowState, xMax: -10 }, xResolution: 1 }), /minimum/);
console.log("graphing-demo: coordinate, discontinuity, Circle, and buffer checks passed");
