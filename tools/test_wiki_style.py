#!/usr/bin/env python3
"""Check source-level wiki conventions that have unambiguous fixes."""

from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CONTENT_PAGES = sorted(path for path in DOCS.glob("*.md") if path.name != "SUMMARY.md")
MARKDOWN_FILES = [ROOT / "README.md", *CONTENT_PAGES]

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
SUMMARY_LINK = re.compile(r"\[[^]]+\]\(([^)#]+\.md)(?:#[^)]+)?\)")
NUMBERED_HEADING = re.compile(r"^#{2,6}\s+\d+(?:\.\d+|[a-z])?\.?\s+")
NUMBERED_REFERENCE = re.compile(r"§\s*\d")
LINK_IN_HEADING = re.compile(r"^#{1,6}\s+.*\[[^]]+\]\([^)]+\)")
BOLD_CONFIDENCE = re.compile(r"\*\*\[(?:confirmed|standard|hypothesis)\]\*\*")
NONSTANDARD_BULLET = re.compile(r"^\s*[+*]\s+")
PROVENANCE_PHRASES = re.compile(
    r"\b(?:Claude|multi-agent)\b|MCP-confirmed|How this RE was produced",
    re.IGNORECASE,
)
VAGUE_HEADING = re.compile(r"^(?:TL;DR|Takeaway|Findings|Notes|Summary)$", re.IGNORECASE)
INLINE_CODE = re.compile(r"(?<!`)`([^`]+)`(?!`)")
Z80_INSTRUCTION_AFTER_SEMICOLON = re.compile(
    r";\s*(?:ADC|ADD|AND|BIT|CALL|CCF|CP|CPD|CPDR|CPI|CPIR|CPL|DAA|DEC|DI|"
    r"DJNZ|EI|EX|EXX|HALT|IM|IN|INC|IND|INDR|INI|INIR|JP|JR|LD|LDD|LDDR|"
    r"LDI|LDIR|NEG|NOP|OR|OTDR|OTIR|OUT|OUTD|OUTI|POP|PUSH|RES|RET|RETI|"
    r"RETN|RL|RLA|RLC|RLCA|RLD|RR|RRA|RRC|RRCA|RRD|RST|SBC|SCF|SET|SLA|"
    r"SLL|SRA|SRL|SUB|XOR|\.db|\.dw|\.byte|\.word)\b"
)


def prose_lines(path: Path) -> list[tuple[int, str]]:
    """Return Markdown lines outside fenced code blocks."""

    result: list[tuple[int, str]] = []
    fence: str | None = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.lstrip()
        marker = stripped[:3]
        if marker in {"```", "~~~"}:
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is None:
            result.append((number, line))
    return result


def findings(pattern: re.Pattern[str], paths: list[Path]) -> list[str]:
    matches: list[str] = []
    for path in paths:
        for number, line in prose_lines(path):
            if pattern.search(line):
                matches.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    return matches


class WikiStyleTests(unittest.TestCase):
    def test_each_page_has_one_title_and_an_overview(self) -> None:
        problems: list[str] = []
        for path in CONTENT_PAGES:
            lines = prose_lines(path)
            titles = [(number, line) for number, line in lines if line.startswith("# ")]
            if len(titles) != 1:
                problems.append(f"{path.relative_to(ROOT)}: expected one H1, found {len(titles)}")
                continue

            title_number = titles[0][0]
            first_h2 = next(
                (number for number, line in lines if number > title_number and line.startswith("## ")),
                None,
            )
            boundary = first_h2 if first_h2 is not None else 1 << 30
            overview = [
                line.strip()
                for number, line in lines
                if title_number < number < boundary
                and line.strip()
                and not line.lstrip().startswith(("<!--", "[!"))
            ]
            if not overview:
                problems.append(f"{path.relative_to(ROOT)}: missing overview before first H2")

        self.assertEqual([], problems, "\n" + "\n".join(problems))

    def test_headings_are_stable_reader_labels(self) -> None:
        problems: list[str] = []
        for path in MARKDOWN_FILES:
            for number, line in prose_lines(path):
                match = HEADING.match(line)
                if match is None:
                    continue
                label = match.group(2)
                if NUMBERED_HEADING.match(line):
                    problems.append(f"{path.relative_to(ROOT)}:{number}: manual section number")
                if LINK_IN_HEADING.match(line):
                    problems.append(f"{path.relative_to(ROOT)}:{number}: link in heading")
                if "&" in label:
                    problems.append(f"{path.relative_to(ROOT)}:{number}: ampersand in heading")
                if VAGUE_HEADING.fullmatch(label):
                    problems.append(f"{path.relative_to(ROOT)}:{number}: vague heading {label!r}")

        self.assertEqual([], problems, "\n" + "\n".join(problems))

    def test_source_uses_canonical_markers(self) -> None:
        problems = [
            *findings(NUMBERED_REFERENCE, MARKDOWN_FILES),
            *findings(BOLD_CONFIDENCE, MARKDOWN_FILES),
            *findings(NONSTANDARD_BULLET, MARKDOWN_FILES),
        ]
        self.assertEqual([], problems, "\n" + "\n".join(problems))

    def test_reader_prose_omits_tool_provenance(self) -> None:
        problems = findings(PROVENANCE_PHRASES, MARKDOWN_FILES)
        self.assertEqual([], problems, "\n" + "\n".join(problems))

    def test_z80_sequences_use_one_instruction_per_line(self) -> None:
        problems: list[str] = []
        for path in MARKDOWN_FILES:
            text = path.read_text(encoding="utf-8")
            for code in INLINE_CODE.finditer(text):
                if ";" in code.group(1) and code.group(1) != ";":
                    number = text.count("\n", 0, code.start()) + 1
                    problems.append(
                        f"{path.relative_to(ROOT)}:{number}: semicolon-chained inline code"
                    )

            fence_language: str | None = None
            for number, line in enumerate(text.splitlines(), 1):
                fence = re.match(r"^\s*(?:>\s*)?```(.*)$", line)
                if fence is not None:
                    fence_language = None if fence_language is not None else fence.group(1).strip()
                    continue
                if fence_language == "z80" and Z80_INSTRUCTION_AFTER_SEMICOLON.search(line):
                    problems.append(
                        f"{path.relative_to(ROOT)}:{number}: instruction follows Z80 comment marker"
                    )

        self.assertEqual([], problems, "\n" + "\n".join(problems))

    def test_summary_targets_exist(self) -> None:
        summary = DOCS / "SUMMARY.md"
        missing: list[str] = []
        for target in SUMMARY_LINK.findall(summary.read_text(encoding="utf-8")):
            resolved = (summary.parent / target).resolve()
            if not resolved.is_file():
                missing.append(target)
        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
