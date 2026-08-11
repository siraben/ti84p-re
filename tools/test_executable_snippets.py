"""Tests for documented-to-executable assembly snippet matching."""

import unittest
from pathlib import Path

from executable_snippets import (
    ExecutableSnippetError,
    compare_snippets,
    load_assembly_snippets,
    load_markdown_snippets,
    parse_assembly_snippets,
    parse_markdown_snippets,
)

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent


class ExecutableSnippetTests(unittest.TestCase):
    def test_flash_document_examples_match_executable_probe(self):
        manifest = compare_snippets(
            load_markdown_snippets(ROOT / "docs" / "flash-memory.md"),
            load_assembly_snippets(TOOLS / "emulator-probes" / "flash-bcall-usage.asm"),
        )

        self.assertEqual(
            {
                "erase-certificate-sector",
                "erase-flash",
                "erase-flash-page",
                "flash-to-ram",
                "set-flash-lower-bound",
                "write-a-byte",
                "write-a-byte-safe",
                "write-flash",
                "write-flash-unsafe",
            },
            set(manifest),
        )

    def test_parser_and_comparison_preserve_exact_text(self):
        documented = parse_markdown_snippets(
            "<!-- executable-snippet: sample -->\n```z80\n    ld a,$08\n```\n"
        )
        executable = parse_assembly_snippets(
            "; executable-snippet-begin: sample\n"
            "    ld a,$08\n"
            "; executable-snippet-end: sample\n"
        )

        manifest = compare_snippets(documented, executable)

        self.assertEqual(1, manifest["sample"]["line_count"])

    def test_comparison_rejects_instruction_drift(self):
        documented = parse_markdown_snippets(
            "<!-- executable-snippet: sample -->\n```z80\n    ld a,$08\n```\n"
        )
        executable = parse_assembly_snippets(
            "; executable-snippet-begin: sample\n"
            "    ld a,$09\n"
            "; executable-snippet-end: sample\n"
        )

        with self.assertRaisesRegex(ExecutableSnippetError, "differ"):
            compare_snippets(documented, executable)

    def test_markdown_marker_requires_z80_fence(self):
        with self.assertRaisesRegex(ExecutableSnippetError, "z80 fence"):
            parse_markdown_snippets(
                "<!-- executable-snippet: sample -->\n```text\nnop\n```\n"
            )


if __name__ == "__main__":
    unittest.main()
