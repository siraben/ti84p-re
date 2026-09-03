#!/usr/bin/env python3
"""Validate KaTeX expressions in generated mdBook HTML."""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


IGNORED_TAGS = {
    "script",
    "noscript",
    "style",
    "textarea",
    "pre",
    "code",
    "option",
}


@dataclass(frozen=True)
class Delimiter:
    left: str
    right: str
    display: bool


DELIMITERS = (
    Delimiter("$$", "$$", True),
    Delimiter("\\[", "\\]", True),
    Delimiter("\\(", "\\)", False),
    Delimiter("$", "$", False),
)


@dataclass(frozen=True)
class Expression:
    text: str
    display: bool
    line: int


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ignored_depth = 0
        self.chunks: list[tuple[int, str]] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        del attrs
        if tag in IGNORED_TAGS:
            self.ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in IGNORED_TAGS and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.chunks.append((self.getpos()[0], data))


def is_escaped(text: str, offset: int) -> bool:
    backslashes = 0
    offset -= 1
    while offset >= 0 and text[offset] == "\\":
        backslashes += 1
        offset -= 1
    return backslashes % 2 == 1


def next_left_delimiter(text: str, start: int) -> tuple[int, Delimiter] | None:
    candidates: list[tuple[int, int, Delimiter]] = []
    for delimiter in DELIMITERS:
        offset = text.find(delimiter.left, start)
        while offset >= 0 and is_escaped(text, offset):
            offset = text.find(delimiter.left, offset + len(delimiter.left))
        if offset >= 0:
            candidates.append((offset, -len(delimiter.left), delimiter))
    if not candidates:
        return None
    offset, _, delimiter = min(candidates, key=lambda candidate: candidate[:2])
    return offset, delimiter


def find_right_delimiter(text: str, start: int, delimiter: Delimiter) -> int | None:
    depth = 0
    offset = start
    while offset < len(text):
        if depth == 0 and text.startswith(delimiter.right, offset):
            return offset
        char = text[offset]
        if char == "\\":
            offset += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}" and depth:
            depth -= 1
        offset += 1
    return None


def expressions(chunk_line: int, text: str) -> tuple[list[Expression], list[str]]:
    found: list[Expression] = []
    findings: list[str] = []
    cursor = 0
    while match := next_left_delimiter(text, cursor):
        left_offset, delimiter = match
        content_start = left_offset + len(delimiter.left)
        right_offset = find_right_delimiter(text, content_start, delimiter)
        line = chunk_line + text.count("\n", 0, left_offset)
        if right_offset is None:
            findings.append(f"line {line}: unmatched {delimiter.left!r} delimiter")
            cursor = content_start
            continue
        found.append(
            Expression(
                text=text[content_start:right_offset],
                display=delimiter.display,
                line=line,
            )
        )
        cursor = right_offset + len(delimiter.right)
    return found, findings


def validate_expression(katex: str, expression: Expression) -> str | None:
    command = [katex]
    if expression.display:
        command.append("--display-mode")
    result = subprocess.run(
        command,
        input=expression.text,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode == 0:
        return None
    detail = " ".join(result.stderr.strip().splitlines())
    return detail or f"KaTeX exited with status {result.returncode}"


def main() -> int:
    if len(sys.argv) not in (2, 3):
        print("usage: python3 -m ti84re.wiki.check_katex_output OUT_DIR [KATEX_BIN]", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    katex = sys.argv[2] if len(sys.argv) == 3 else shutil.which("katex")
    if not katex:
        print("check_katex_output: katex executable not found", file=sys.stderr)
        return 2

    findings: list[str] = []
    expression_count = 0
    validated: dict[tuple[str, bool], str | None] = {}

    for page in sorted(root.rglob("*.html")):
        parser = TextParser()
        parser.feed(page.read_text(encoding="utf-8", errors="replace"))
        relative = page.relative_to(root)
        for chunk_line, chunk in parser.chunks:
            chunk_expressions, chunk_findings = expressions(chunk_line, chunk)
            findings.extend(f"{relative}:{finding}" for finding in chunk_findings)
            for expression in chunk_expressions:
                expression_count += 1
                key = (expression.text, expression.display)
                if key not in validated:
                    validated[key] = validate_expression(katex, expression)
                if error := validated[key]:
                    findings.append(f"{relative}:line {expression.line}: {error}")

    if findings:
        print("generated KaTeX validation failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1

    print(
        "generated KaTeX validation passed "
        f"({expression_count} expressions, {len(validated)} unique)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
