#!/usr/bin/env python3
"""Tests for numeric community bcall discovery."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_community_bcalls import scan_file


class ScanFileTest(unittest.TestCase):
    def scan(self, text: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.z80"
            path.write_text(text, encoding="utf-8")
            return scan_file(path)

    def test_macro_forms(self):
        findings = self.scan("bcall(4F66h)\nB_CALL $50CE\n")
        self.assertEqual([0x4F66, 0x50CE], [row.identifier for row in findings])
        self.assertEqual(["macro", "macro"], [row.form for row in findings])

    def test_raw_rst_word(self):
        findings = self.scan("rst 28h\n.dw $5221\n")
        self.assertEqual([0x5221], [row.identifier for row in findings])
        self.assertEqual("raw-rst", findings[0].form)

    def test_raw_opcode_bytes(self):
        findings = self.scan(".db $EF,$C4,$45 ; native bcall\n")
        self.assertEqual([0x45C4], [row.identifier for row in findings])
        self.assertEqual("raw-bytes", findings[0].form)

    def test_ignores_comments_and_definitions(self):
        findings = self.scan(
            "#define bcall(x) rst 28h \\ .dw x\n"
            "; bcall(4F66h)\n"
            "bcall(_PutS)\n"
            "B_CALL defenitionpg1\n"
        )
        self.assertEqual([], findings)


if __name__ == "__main__":
    unittest.main()
