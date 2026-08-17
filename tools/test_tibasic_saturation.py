#!/usr/bin/env python3
"""Regression tests for bounded TI-BASIC saturation evidence."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from analyze_tibasic_saturation import components, parser_table
from rom_image import RomImage, RomLocation


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "tools" / "rom.bin"
REPORT = ROOT / "tools" / "tibasic-saturation.json"


class TiBasicSaturationTests(unittest.TestCase):
    @unittest.skipUnless(ROM.is_file(), "pinned ROM not present")
    def test_parser_table_seeds_every_valid_rom_pointer(self) -> None:
        rom = RomImage.from_path(ROM)
        table = parser_table(rom)
        self.assertEqual(table["slots"], 87)
        self.assertEqual(table["valid_pointer_slots"], 84)
        self.assertEqual(table["unique_handler_entries"], 81)
        self.assertEqual(table["invalid_slots"], [24, 85, 86])

    @unittest.skipUnless(ROM.is_file(), "pinned ROM not present")
    def test_loop_and_end_handlers_are_parser_roots(self) -> None:
        parser = components(RomImage.from_path(ROM))[0]
        self.assertIn(RomLocation(0x38, 0x41E5), parser.entries)
        self.assertIn(RomLocation(0x38, 0x4200), parser.entries)

    def test_checked_report_is_explicitly_partial_and_compact(self) -> None:
        report = json.loads(REPORT.read_text())
        self.assertFalse(report["scope"]["complete"])
        self.assertEqual(report["static"]["reachable_instructions"], 7651)
        self.assertEqual(report["static"]["conditional_branches"], 1230)
        self.assertEqual(report["static"]["possible_outcomes"], 2460)
        self.assertEqual(report["dynamic"]["outcomes_observed"], 728)
        self.assertEqual(report["dynamic"]["natural_outcomes_observed"], 699)
        self.assertLess(REPORT.stat().st_size, 50_000)

    def test_natural_component_coverage_does_not_include_probe_dispatch(self) -> None:
        report = json.loads(REPORT.read_text())
        rows = {row["name"]: row for row in report["dynamic"]["components"]}
        self.assertEqual(rows["control_flow"]["natural_outcomes_observed"], 0)
        self.assertEqual(rows["value_storage"]["natural_outcomes_observed"], 111)
        self.assertEqual(rows["numeric_errors"]["natural_outcomes_observed"], 4)

    def test_declared_computed_dispatches_have_bounded_destinations(self) -> None:
        report = json.loads(REPORT.read_text())
        dispatches = {
            row["location"]: row["destinations"]
            for row in report["computed_dispatches"]
        }
        self.assertEqual(
            dispatches,
            {"38:4390": 14, "38:7244": 27, "02:5675": 5, "33:4380": 13},
        )
        self.assertTrue(
            all(not row["unresolved"] for row in report["static"]["components"])
        )


if __name__ == "__main__":
    unittest.main()
