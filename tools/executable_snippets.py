"""Match documented assembly snippets to regions of an executable fixture."""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

MARKDOWN_MARKER = re.compile(
    r"\s*<!--\s*executable-snippet:\s*([a-z0-9][a-z0-9-]*)\s*-->\s*"
)
ASSEMBLY_BEGIN = re.compile(
    r"\s*;\s*executable-snippet-begin:\s*([a-z0-9][a-z0-9-]*)\s*"
)
ASSEMBLY_END = re.compile(r"\s*;\s*executable-snippet-end:\s*([a-z0-9][a-z0-9-]*)\s*")


class ExecutableSnippetError(ValueError):
    """A tagged snippet is malformed or differs from its executable source."""


@dataclass(frozen=True)
class ExecutableSnippet:
    """One named source region with stable text and location."""

    name: str
    text: str
    start_line: int

    @property
    def sha256(self) -> str:
        return sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def line_count(self) -> int:
        return len(self.text.splitlines())


def _insert(
    snippets: dict[str, ExecutableSnippet],
    snippet: ExecutableSnippet,
    *,
    source: str,
) -> None:
    if snippet.name in snippets:
        raise ExecutableSnippetError(
            f"{source}:{snippet.start_line}: duplicate snippet {snippet.name!r}"
        )
    snippets[snippet.name] = snippet


def parse_markdown_snippets(
    text: str, *, source: str = "<markdown>"
) -> dict[str, ExecutableSnippet]:
    """Extract tagged ``z80`` fences from Markdown text."""

    lines = text.splitlines()
    snippets: dict[str, ExecutableSnippet] = {}
    index = 0
    while index < len(lines):
        marker = MARKDOWN_MARKER.fullmatch(lines[index])
        if marker is None:
            index += 1
            continue
        name = marker.group(1)
        marker_line = index + 1
        index += 1
        while index < len(lines) and not lines[index].strip():
            index += 1
        if index >= len(lines) or lines[index].strip() != "```z80":
            raise ExecutableSnippetError(
                f"{source}:{marker_line}: snippet {name!r} must precede a z80 fence"
            )
        fence_line = index + 1
        index += 1
        body: list[str] = []
        while index < len(lines) and lines[index].strip() != "```":
            body.append(lines[index])
            index += 1
        if index >= len(lines):
            raise ExecutableSnippetError(
                f"{source}:{fence_line}: unterminated snippet {name!r}"
            )
        snippet = ExecutableSnippet(name, "\n".join(body) + "\n", fence_line + 1)
        _insert(snippets, snippet, source=source)
        index += 1
    return snippets


def parse_assembly_snippets(
    text: str, *, source: str = "<assembly>"
) -> dict[str, ExecutableSnippet]:
    """Extract semicolon-tagged regions from assembly text."""

    lines = text.splitlines()
    snippets: dict[str, ExecutableSnippet] = {}
    active_name: str | None = None
    active_line = 0
    body: list[str] = []
    for index, line in enumerate(lines, start=1):
        begin = ASSEMBLY_BEGIN.fullmatch(line)
        end = ASSEMBLY_END.fullmatch(line)
        if begin is not None:
            if active_name is not None:
                raise ExecutableSnippetError(
                    f"{source}:{index}: nested snippet {begin.group(1)!r}"
                )
            active_name = begin.group(1)
            active_line = index + 1
            body = []
            continue
        if end is not None:
            if active_name is None:
                raise ExecutableSnippetError(
                    f"{source}:{index}: unmatched snippet end {end.group(1)!r}"
                )
            if end.group(1) != active_name:
                raise ExecutableSnippetError(
                    f"{source}:{index}: snippet end {end.group(1)!r} does not match "
                    f"{active_name!r}"
                )
            snippet = ExecutableSnippet(
                active_name, "\n".join(body) + "\n", active_line
            )
            _insert(snippets, snippet, source=source)
            active_name = None
            body = []
            continue
        if active_name is not None:
            body.append(line)
    if active_name is not None:
        raise ExecutableSnippetError(
            f"{source}:{active_line - 1}: unterminated snippet {active_name!r}"
        )
    return snippets


def load_markdown_snippets(path: Path) -> dict[str, ExecutableSnippet]:
    return parse_markdown_snippets(path.read_text(encoding="utf-8"), source=str(path))


def load_assembly_snippets(path: Path) -> dict[str, ExecutableSnippet]:
    return parse_assembly_snippets(path.read_text(encoding="utf-8"), source=str(path))


def compare_snippets(
    documented: dict[str, ExecutableSnippet],
    executable: dict[str, ExecutableSnippet],
) -> dict[str, dict[str, object]]:
    """Require identical names and bytes, returning a compact manifest."""

    missing_from_executable = sorted(documented.keys() - executable.keys())
    missing_from_docs = sorted(executable.keys() - documented.keys())
    if missing_from_executable or missing_from_docs:
        raise ExecutableSnippetError(
            "snippet sets differ: "
            f"missing from executable={missing_from_executable}, "
            f"missing from docs={missing_from_docs}"
        )
    mismatches = [
        name
        for name in sorted(documented)
        if documented[name].text != executable[name].text
    ]
    if mismatches:
        raise ExecutableSnippetError(
            "documented snippets differ from executable regions: "
            + ", ".join(mismatches)
        )
    return {
        name: {
            "sha256": documented[name].sha256,
            "line_count": documented[name].line_count,
            "markdown_line": documented[name].start_line,
            "assembly_line": executable[name].start_line,
        }
        for name in sorted(documented)
    }
