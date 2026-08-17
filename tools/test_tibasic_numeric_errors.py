#!/usr/bin/env python3
"""Regression tests for compact TI-BASIC numeric-error provenance."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from analyze_tibasic_numeric_errors import EXAMPLES
from rom_image import RomImage


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "tools" / "rom.bin"
REPORT = ROOT / "tools" / "tibasic-numeric-errors.json"


class TiBasicNumericErrorTests(unittest.TestCase):
    @unittest.skipUnless(ROM.is_file(), "pinned ROM not present")
    def test_error_guards_match_pinned_rom(self) -> None:
        rom = RomImage.from_path(ROM)
        expected = {
            (0x00, 0x254B): bytes.fromhex("CAEC26"),
            (0x02, 0x7059): bytes.fromhex("C3E826"),
            (0x00, 0x251D): bytes.fromhex("C3E826"),
            (0x00, 0x212D): bytes.fromhex("CDE91D"),
            (0x00, 0x2131): bytes.fromhex("18EA"),
            (0x37, 0x4268): bytes.fromhex("CDE91D"),
            (0x37, 0x426B): bytes.fromhex("CAF826"),
        }
        for (page, address), data in expected.items():
            with self.subTest(page=page, address=address):
                self.assertEqual(rom.bytes_at(page, address, len(data)), data)

    def test_examples_have_distinct_guard_paths(self) -> None:
        paths = {example.path for example in EXAMPLES.values()}
        self.assertEqual(len(paths), len(EXAMPLES))
        self.assertEqual(len(EXAMPLES), 5)

    def test_checked_report_verifies_every_example(self) -> None:
        report = json.loads(REPORT.read_text())
        self.assertFalse(report["scope"]["complete"])
        self.assertEqual(report["summary"], {
            "examples": 5,
            "distinct_errors": 4,
            "distinct_guard_paths": 5,
            "verified": 5,
        })
        self.assertTrue(all(row["verified"] for row in report["examples"]))
        self.assertTrue(all(not row["missing_path"] for row in report["examples"]))
        self.assertLess(REPORT.stat().st_size, 12_000)


if __name__ == "__main__":
    unittest.main()
