// Render ```pseudocode fenced blocks as typeset algorithms via pseudocode.js.
// pseudocode.js uses KaTeX for the math, so katex.min.js must load before this.
(function () {
  function render() {
    if (typeof pseudocode === "undefined") return;
    var blocks = document.querySelectorAll("code.language-pseudocode");
    for (var i = 0; i < blocks.length; i++) {
      var code = blocks[i];
      var pre = code.parentElement && code.parentElement.tagName === "PRE" ? code.parentElement : code;
      try {
        var html = pseudocode.renderToString(code.textContent, {
          lineNumber: true,
          noEnd: false,
        });
        var wrap = document.createElement("div");
        wrap.className = "pseudocode-rendered";
        wrap.innerHTML = html;
        pre.parentNode.replaceChild(wrap, pre);
      } catch (e) {
        // On a syntax error leave the raw block in place so nothing is lost.
        if (window.console) console.error("pseudocode render error:", e);
      }
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", render);
  } else {
    render();
  }
})();
