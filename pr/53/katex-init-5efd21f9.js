// Render LaTeX math with KaTeX's auto-render extension (client-side, offline).
// renderMathInElement skips <code>/<pre>/<script>/<style> by default, so the
// hex literals like `$1A2F` inside Z80 code blocks are never treated as math.
(function () {
  function render() {
    if (typeof renderMathInElement !== "function") return;
    renderMathInElement(document.body, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "\\[", right: "\\]", display: true },
        { left: "$", right: "$", display: false },
        { left: "\\(", right: "\\)", display: false },
      ],
      // Belt-and-braces: auto-render already ignores these tags, but be explicit.
      ignoredTags: ["script", "noscript", "style", "textarea", "pre", "code", "option"],
      throwOnError: false,
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", render);
  } else {
    render();
  }
})();
