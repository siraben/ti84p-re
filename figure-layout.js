// Mermaid measures labels before emitting an SVG. Keep wide figures legible
// after mdBook places them in an article column or a narrow viewport.
for (const diagram of document.querySelectorAll("pre.mermaid")) {
    function sizeDiagram() {
        const svg = diagram.querySelector("svg");
        const width = svg?.viewBox.baseVal.width;
        if (!width) return false;
        // Mermaid's 16px labels can shrink to 13px before local scrolling starts.
        svg.style.setProperty("--readable-width", (width * 13 / 16) + "px");
        return true;
    }

    if (!sizeDiagram()) {
        const observer = new MutationObserver(() => {
            if (sizeDiagram()) observer.disconnect();
        });
        observer.observe(diagram, { childList: true, subtree: true, attributes: true, attributeFilter: ["viewBox"] });
    }
}
