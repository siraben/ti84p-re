#!/usr/bin/env python3
"""Regression tests for compact TI-BASIC numeric-error provenance."""

from __future__ import annotations

import json
import unittest

from ti84re.tibasic.analyze_numeric_errors import EXAMPLES, SHIMS
from ti84re.rom.image import RomImage
from ti84re.paths import ORACLES, DEFAULT_ROM


ROM = DEFAULT_ROM
REPORT = ORACLES / "tibasic/tibasic-numeric-errors.json"


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
            (0x02, 0x76E2): bytes.fromhex("DAF426"),
            (0x02, 0x76F5): bytes.fromhex("DAF426"),
            (0x00, 0x1B93): bytes.fromhex("C2FC26"),
            (0x02, 0x43A5): bytes.fromhex("CAF026"),
            (0x38, 0x5876): bytes.fromhex("CAF826"),
            (0x35, 0x79D2): bytes.fromhex("C2F426"),
            (0x00, 0x211D): bytes.fromhex("C3F426"),
        }
        for (page, address), data in expected.items():
            with self.subTest(page=page, address=address):
                self.assertEqual(rom.bytes_at(page, address, len(data)), data)

    def test_examples_have_distinct_guard_paths(self) -> None:
        paths = {example.path for example in EXAMPLES.values()}
        self.assertEqual(len(paths), len(EXAMPLES))
        self.assertEqual(len(EXAMPLES), 12)

    def test_checked_report_verifies_every_example(self) -> None:
        report = json.loads(REPORT.read_text())
        self.assertFalse(report["scope"]["complete"])
        self.assertEqual(report["schema"], 2)
        self.assertEqual(report["summary"], {
            "examples": 12,
            "distinct_errors": 6,
            "distinct_guard_paths": 12,
            "direct_reference_candidates": 114,
            "distinct_direct_callers_witnessed": 11,
            "verified": 12,
        })
        self.assertTrue(all(row["verified"] for row in report["examples"]))
        self.assertTrue(all(not row["missing_path"] for row in report["examples"]))
        self.assertLess(REPORT.stat().st_size, 30_000)

    def test_direct_reference_inventory_is_rom_pinned(self) -> None:
        report = json.loads(REPORT.read_text())
        rows = report["caller_inventory"]["shims"]
        self.assertEqual(
            {row["entry"]: row["candidate_count"] for row in rows},
            {
                "00:26E8": 9,
                "00:26EC": 2,
                "00:26F0": 3,
                "00:26F4": 91,
                "00:26F8": 6,
                "00:26FC": 3,
            },
        )
        self.assertEqual(
            {(row["error"], int(row["error_code"], 16)) for row in rows},
            set(SHIMS.values()),
        )
        self.assertTrue(all(
            len(row["candidates"]) == row["candidate_count"] for row in rows
        ))
        self.assertTrue(all(
            len(set(row["candidates"])) == len(row["candidates"])
            for row in rows
        ))


if __name__ == "__main__":
    unittest.main()
