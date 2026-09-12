(function () {
  "use strict";
  const M = window.GraphingDemoModel;
  const $ = id => document.getElementById(id);
  const canvas = $("screen");
  const context = canvas.getContext("2d");
  const inputs = ["x-min", "x-max", "y-min", "y-max", "xres", "center-x", "center-y", "radius", "axes", "grid", "scale"];
  let mode = "square";
  let scene = null;
  let timer = null;

  const notes = {
    square: "The retained Y1=X² trace advances curInc through columns 0–94 at Xres=1. This view exposes the sample-to-pixel sequence without claiming the browser evaluation is TI packed BCD.",
    reciprocal: "The retained Y1=X⁻¹ trace enters divide-by-zero handling at state columns 46 and 47. The visible segment ends at column 46 and restarts at 48; no connector crosses the center discontinuity.",
    circle: "The reset-origin Circle(0,0,5) trace selects the clear-flag page-33 generator. It emits 60 continuous _CLine segments; each idealized browser step advances six degrees.",
  };

  function number(id) { return Number($(id).value); }
  function options() {
    return {
      mode,
      window: { xMin: number("x-min"), xMax: number("x-max"), yMin: number("y-min"), yMax: number("y-max") },
      xResolution: number("xres"), centerX: number("center-x"), centerY: number("center-y"), radius: number("radius"),
    };
  }

  function stop() {
    if (timer !== null) window.clearInterval(timer);
    timer = null;
    $("play").textContent = "▶";
  }

  function format(value) {
    if (!Number.isFinite(value)) return "—";
    const magnitude = Math.abs(value);
    return magnitude !== 0 && (magnitude >= 1e5 || magnitude < 1e-4) ? value.toExponential(5) : Number(value.toFixed(8)).toString();
  }

  function setOperation(event, index) {
    const box = $("operation");
    if (!event) { box.innerHTML = "<dt>State</dt><dd>No raster event selected</dd>"; return; }
    box.innerHTML = [
      ["Event", (index + 1) + " / " + scene.events.length],
      ["Kind", event.kind],
      ["Real start", "(" + format(event.from.realX) + ", " + format(event.from.realY) + ")"],
      ["Real end", "(" + format(event.to.realX) + ", " + format(event.to.realY) + ")"],
      ["Pixel line", "(" + event.from.x + ", " + event.from.y + ") → (" + event.to.x + ", " + event.to.y + ")"],
      ["Raster pixels", String(event.pixels.length)],
    ].map(row => "<dt>" + row[0] + "</dt><dd>" + row[1] + "</dd>").join("");
  }

  function draw() {
    if (!scene) return;
    const scale = number("scale");
    canvas.width = M.WIDTH * scale;
    canvas.height = M.HEIGHT * scale;
    context.fillStyle = "#c6d3a4";
    context.fillRect(0, 0, canvas.width, canvas.height);

    if ($("axes").checked) {
      context.fillStyle = "#66765b";
      for (const point of M.axisPixels(scene.window)) context.fillRect(point.x * scale, point.y * scale, scale, scale);
    }
    const count = Number($("timeline").value);
    const pixels = M.pixelsThrough(scene, count);
    context.fillStyle = "#172519";
    for (const key of pixels) {
      const [x, y] = key.split(",").map(Number);
      context.fillRect(x * scale, y * scale, scale, scale);
    }
    if ($("grid").checked && scale >= 5) {
      context.strokeStyle = "rgba(23,37,25,.13)";
      context.lineWidth = 1;
      context.beginPath();
      for (let x = 0; x <= M.WIDTH; x++) { context.moveTo(x * scale + .5, 0); context.lineTo(x * scale + .5, canvas.height); }
      for (let y = 0; y <= M.HEIGHT; y++) { context.moveTo(0, y * scale + .5); context.lineTo(canvas.width, y * scale + .5); }
      context.stroke();
    }
    $("timeline-output").value = count + " / " + scene.events.length;
    $("metric-pixels").textContent = pixels.size;
    setOperation(scene.events[count - 1], count - 1);
  }

  function rebuild() {
    stop();
    try {
      scene = M.createScene(options());
      $("error").textContent = "";
      $("timeline").max = scene.events.length;
      $("timeline").value = scene.events.length;
      $("metric-samples").textContent = scene.samples;
      $("metric-events").textContent = scene.events.length;
      $("metric-breaks").textContent = scene.breaks;
      $("scenario-note").textContent = notes[mode];
      $("xres-output").value = $("xres").value;
      $("scale-output").value = $("scale").value + "×";
      draw();
    } catch (error) {
      scene = null;
      $("error").textContent = error.message;
    }
  }

  document.querySelectorAll(".preset").forEach(button => button.addEventListener("click", () => {
    mode = button.dataset.mode;
    document.querySelectorAll(".preset").forEach(item => item.classList.toggle("active", item === button));
    $("circle-controls").hidden = mode !== "circle";
    $("function-controls").hidden = mode === "circle";
    rebuild();
  }));
  inputs.forEach(id => $(id).addEventListener("input", id === "scale" || id === "axes" || id === "grid" ? () => { if (scene) { $("scale-output").value = $("scale").value + "×"; draw(); } } : rebuild));
  $("timeline").addEventListener("input", () => { stop(); draw(); });
  $("play").addEventListener("click", () => {
    if (!scene) return;
    if (timer !== null) { stop(); return; }
    if (Number($("timeline").value) >= scene.events.length) $("timeline").value = 0;
    $("play").textContent = "Ⅱ";
    timer = window.setInterval(() => {
      const next = Number($("timeline").value) + 1;
      $("timeline").value = next;
      draw();
      if (next >= scene.events.length) stop();
    }, mode === "circle" ? 55 : 35);
  });
  canvas.addEventListener("mousemove", event => {
    if (!scene) return;
    const rect = canvas.getBoundingClientRect();
    const x = Math.max(0, Math.min(95, Math.floor((event.clientX - rect.left) * M.WIDTH / rect.width)));
    const y = Math.max(0, Math.min(63, Math.floor((event.clientY - rect.top) * M.HEIGHT / rect.height)));
    const real = M.pixelToReal(x, y, scene.window);
    $("cursor-readout").textContent = "pixel (" + x + ", " + y + ")  ≈  real (" + format(real.x) + ", " + format(real.y) + ")";
  });
  canvas.addEventListener("mouseleave", () => { $("cursor-readout").textContent = "Move over the LCD to inspect a pixel."; });
  rebuild();
})();
