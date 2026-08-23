#!/usr/bin/env python3
"""Validate every Mermaid diagram and rendered math block in the built wiki.

The source/HTML inventory catches content lost during Markdown conversion. A
headless Chromium pass over print.html then exercises the same client-side
Mermaid, KaTeX, and pseudocode.js assets that the deployed wiki loads. Each
content-bearing page is also loaded separately to catch page-local JavaScript
failures that print.html could mask.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


SUMMARY_LINK = re.compile(r"\[[^]]+\]\(([^)#]+\.md)(?:#[^)]+)?\)")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
}


def load_katex_checker():
    path = Path(__file__).with_name("check-katex-output.py")
    spec = importlib.util.spec_from_file_location("check_katex_output", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


KATEX_CHECKER = load_katex_checker()


@dataclass(frozen=True)
class Inventory:
    math: int = 0
    mermaid: int = 0
    pseudocode: int = 0

    def __add__(self, other: "Inventory") -> "Inventory":
        return Inventory(
            self.math + other.math,
            self.mermaid + other.mermaid,
            self.pseudocode + other.pseudocode,
        )


def strip_inline_code(line: str) -> str:
    """Replace Markdown code spans while preserving offsets and newlines."""

    result = list(line)
    cursor = 0
    while cursor < len(line):
        if line[cursor] != "`":
            cursor += 1
            continue
        end = cursor
        while end < len(line) and line[end] == "`":
            end += 1
        marker = line[cursor:end]
        close = line.find(marker, end)
        if close < 0:
            cursor = end
            continue
        for offset in range(cursor, close + len(marker)):
            result[offset] = " "
        cursor = close + len(marker)
    return "".join(result)


def markdown_inventory(path: Path) -> tuple[Inventory, list[str]]:
    prose: list[str] = []
    mermaid = 0
    pseudocode = 0
    fence_char = ""
    fence_length = 0

    for line in path.read_text(encoding="utf-8").splitlines(keepends=True):
        match = FENCE.match(line)
        if not fence_char:
            if match:
                marker, info = match.groups()
                fence_char = marker[0]
                fence_length = len(marker)
                language = info.strip().split(None, 1)[0] if info.strip() else ""
                mermaid += language == "mermaid"
                pseudocode += language == "pseudocode"
            else:
                prose.append(strip_inline_code(line))
        elif match and match.group(1)[0] == fence_char and len(match.group(1)) >= fence_length:
            fence_char = ""
            fence_length = 0

    text = "".join(prose)
    expressions, findings = KATEX_CHECKER.expressions(1, text)
    if fence_char:
        findings.append("unclosed fenced code block")
    return Inventory(len(expressions), mermaid, pseudocode), findings


class StructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.mermaids: list[dict[str, bool]] = []
        self.active_mermaid: tuple[int, int] | None = None
        self.depth = 0
        self.pseudocode_source = 0
        self.pseudocode_rendered = 0
        self.katex = 0
        self.katex_error = 0
        self.mermaid_errors = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = {key: value for key, value in attrs if value is not None}
        classes = set(values.get("class", "").split())
        next_depth = self.depth + (tag not in VOID_TAGS)

        if "mermaid" in classes:
            self.mermaids.append(
                {"processed": values.get("data-processed") == "true", "svg": False}
            )
            self.active_mermaid = (next_depth, len(self.mermaids) - 1)
        if tag == "svg" and self.active_mermaid is not None:
            self.mermaids[self.active_mermaid[1]]["svg"] = True
        if values.get("aria-roledescription") == "error" or "error-icon" in classes:
            self.mermaid_errors += 1
        if tag == "code" and "language-pseudocode" in classes:
            self.pseudocode_source += 1
        if "pseudocode-rendered" in classes:
            self.pseudocode_rendered += 1
        if "katex" in classes:
            self.katex += 1
        if "katex-error" in classes:
            self.katex_error += 1

        if tag not in VOID_TAGS:
            self.depth += 1

    def handle_endtag(self, tag: str) -> None:
        del tag
        if self.active_mermaid is not None and self.depth == self.active_mermaid[0]:
            self.active_mermaid = None
        if self.depth:
            self.depth -= 1


def html_inventory(path: Path) -> tuple[Inventory, list[str]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    structure = StructureParser()
    structure.feed(raw)

    text_parser = KATEX_CHECKER.TextParser()
    text_parser.feed(raw)
    math = 0
    findings: list[str] = []
    for line, chunk in text_parser.chunks:
        expressions, chunk_findings = KATEX_CHECKER.expressions(line, chunk)
        math += len(expressions)
        findings.extend(chunk_findings)
    return Inventory(math, len(structure.mermaids), structure.pseudocode_source), findings


def browser_dom(chromium: str, page: Path, virtual_time_ms: int) -> str:
    with tempfile.TemporaryDirectory(prefix="wiki-render-") as temp:
        temp_path = Path(temp)
        env = os.environ.copy()
        env.update({"HOME": temp, "XDG_CACHE_HOME": temp, "XDG_CONFIG_HOME": temp})
        result = subprocess.run(
            [
                chromium,
                "--headless",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--allow-file-access-from-files",
                "--enable-logging=stderr",
                "--v=0",
                "--run-all-compositor-stages-before-draw",
                f"--virtual-time-budget={virtual_time_ms}",
                f"--user-data-dir={temp_path / 'profile'}",
                "--dump-dom",
                page.as_uri(),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            env=env,
            check=False,
        )
    if result.returncode:
        detail = " ".join(result.stderr.strip().splitlines()[-10:])
        raise RuntimeError(f"Chromium exited with status {result.returncode}: {detail}")
    console_failures = [
        line.strip()
        for line in result.stderr.splitlines()
        if "INFO:CONSOLE" in line
        and ('"Uncaught ' in line or '"pseudocode render error:' in line)
    ]
    if console_failures:
        raise RuntimeError("JavaScript console failure: " + " | ".join(console_failures))
    return result.stdout


def rendered_findings(label: str, rendered: str, expected: Inventory) -> list[str]:
    findings: list[str] = []
    structure = StructureParser()
    structure.feed(rendered)
    text_parser = KATEX_CHECKER.TextParser()
    text_parser.feed(rendered)
    raw_math = 0
    for line, chunk in text_parser.chunks:
        expressions, chunk_findings = KATEX_CHECKER.expressions(line, chunk)
        raw_math += len(expressions)
        findings.extend(f"{label}: {finding}" for finding in chunk_findings)

    if len(structure.mermaids) != expected.mermaid:
        findings.append(
            f"{label}: {len(structure.mermaids)} Mermaid containers, "
            f"expected {expected.mermaid}"
        )
    for index, diagram in enumerate(structure.mermaids, 1):
        if not diagram["processed"] or not diagram["svg"]:
            findings.append(f"{label}: Mermaid diagram {index} did not render")
    if structure.mermaid_errors:
        findings.append(f"{label}: {structure.mermaid_errors} Mermaid error markers")
    if structure.katex_error:
        findings.append(f"{label}: {structure.katex_error} KaTeX errors")
    if structure.katex < expected.math:
        findings.append(
            f"{label}: {structure.katex} KaTeX roots, expected at least {expected.math}"
        )
    if raw_math:
        findings.append(f"{label}: {raw_math} raw math expressions remain")
    if structure.pseudocode_source:
        findings.append(
            f"{label}: {structure.pseudocode_source} raw pseudocode blocks remain"
        )
    if structure.pseudocode_rendered != expected.pseudocode:
        findings.append(
            f"{label}: {structure.pseudocode_rendered} pseudocode renderings, "
            f"expected {expected.pseudocode}"
        )
    return findings


def main() -> int:
    if len(sys.argv) not in (3, 4):
        print(
            "usage: check-wiki-rendering.py DOCS_DIR OUT_DIR [CHROMIUM_BIN]",
            file=sys.stderr,
        )
        return 2

    docs = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2]).resolve()
    chromium = sys.argv[3] if len(sys.argv) == 4 else shutil.which("chromium")
    if not chromium:
        print("check-wiki-rendering.py: chromium executable not found", file=sys.stderr)
        return 2

    summary = (docs / "SUMMARY.md").read_text(encoding="utf-8")
    targets = list(dict.fromkeys(SUMMARY_LINK.findall(summary)))
    findings: list[str] = []
    source_total = Inventory()
    html_total = Inventory()
    page_inventories: list[tuple[str, Path, Inventory]] = []

    for target in targets:
        source = docs / target
        page = out / Path(target).with_suffix(".html")
        source_inventory, source_findings = markdown_inventory(source)
        html_page_inventory, html_findings = html_inventory(page)
        source_total += source_inventory
        html_total += html_page_inventory
        page_inventories.append((target, page, source_inventory))
        findings.extend(f"{target}: {finding}" for finding in source_findings)
        findings.extend(f"{page.name}: {finding}" for finding in html_findings)
        if source_inventory != html_page_inventory:
            findings.append(
                f"{target}: source {source_inventory} != generated {html_page_inventory}"
            )

    print_page = out / "print.html"
    print_inventory, print_findings = html_inventory(print_page)
    findings.extend(f"print.html: {finding}" for finding in print_findings)
    if print_inventory != source_total:
        findings.append(
            f"print.html: inventory {print_inventory} != source total {source_total}"
        )

    if findings:
        print("wiki source/render inventory failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1

    for target, page, inventory in page_inventories:
        if inventory == Inventory():
            continue
        try:
            rendered = browser_dom(chromium, page, 10000)
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            findings.append(f"{target}: Chromium failed: {error}")
            continue
        findings.extend(rendered_findings(target, rendered, inventory))

    try:
        rendered = browser_dom(chromium, print_page, 30000)
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        findings.append(f"print.html: Chromium failed: {error}")
    else:
        findings.extend(rendered_findings("print.html", rendered, source_total))

    if findings:
        print("wiki browser rendering failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1

    print(
        "wiki browser rendering passed "
        f"({source_total.mermaid} Mermaid diagrams, "
        f"{source_total.math} KaTeX expressions, "
        f"{source_total.pseudocode} pseudocode blocks)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
