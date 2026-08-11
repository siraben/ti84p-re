#!/usr/bin/env python3
"""Regression tests for the pinned TilEm battery-comparator probe."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tilem_battery import (
    TilemBatteryError,
    TilemBatteryReport,
    build_command,
    expected_battery_report,
    parse_battery_report,
    validate_battery_report,
)

NATIVE_REPORT = " ".join(  # noqa: FLY002 - readable native fixture
    (
        "mode=tilem-battery-probe reset_battery=60 reset_port4=07",
        "reset_status=E3 voltages=30,31,32,33,34,35,36,37,38,39,40,41,42,43,44,45",
        "masks=0,0,0,1,1,1,5,5,5,7,7,7,7,F,F,F",
        "levels=0,0,0,1,1,1,3,3,3,3,3,3,3,4,4,4",
    )
)


class TilemBatteryReportTests(unittest.TestCase):
    def test_parser_decodes_complete_native_sweep(self):
        report = parse_battery_report(NATIVE_REPORT)

        self.assertIsInstance(report, TilemBatteryReport)
        self.assertEqual(0xE3, report.reset_status)
        self.assertEqual(0x0F, report.masks[-1])
        self.assertEqual(4, report.levels[-1])

    def test_oracle_pins_threshold_transitions(self):
        report = expected_battery_report()

        self.assertEqual(0x01, report.masks[3])
        self.assertEqual(0x05, report.masks[6])
        self.assertEqual(0x07, report.masks[9])
        self.assertEqual(0x0F, report.masks[13])

    def test_oracle_exposes_unreachable_level_two(self):
        validated = validate_battery_report(parse_battery_report(NATIVE_REPORT))

        self.assertEqual([0, 1, 3, 4], validated["source_model"]["reachable_rom_levels"])
        self.assertEqual([2], validated["source_model"]["unreachable_rom_levels"])
        self.assertFalse(validated["source_model"]["physical_scope"])

    def test_oracle_rejects_changed_threshold(self):
        expected = expected_battery_report()
        changed_masks = expected.masks[:3] + (0,) + expected.masks[4:]
        changed = replace(expected, masks=changed_masks)
        with self.assertRaisesRegex(TilemBatteryError, "disagrees"):
            validate_battery_report(changed)

    def test_parser_rejects_short_sweep(self):
        malformed = NATIVE_REPORT.replace(
            "levels=0,0,0,1,1,1,3,3,3,3,3,3,3,4,4,4",
            "levels=0",
        )
        with self.assertRaisesRegex(TilemBatteryError, "must contain 16"):
            parse_battery_report(malformed)

    @patch("tilem_battery.build_core_command", return_value=["cc", "probe"])
    def test_build_command_adds_shared_support(self, build_core):
        command = build_command(
            Path("/tmp/tilem"),
            Path("tools/tilem_battery_probe.c"),
            Path("/tmp/tilem-battery-probe"),
        )

        self.assertEqual(["cc", "probe"], command)
        adapters = build_core.call_args.args[1]
        self.assertEqual("tilem_probe_support.c", adapters[0].name)
        self.assertEqual("tilem_battery_probe.c", adapters[1].name)


if __name__ == "__main__":
    unittest.main()
