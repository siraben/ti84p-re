#!/usr/bin/env python3
"""Regression tests for the direct-entry retail LCD-helper oracle."""

import unittest

from wabbitemu_headless import (
    WabbitemuHeadlessError,
    WabbitemuLcdDiagnosticReport,
    parse_lcd_diagnostic_report,
)
from wabbitemu_lcd_diagnostic_probe import (
    expected_lcd_diagnostic_values,
    validate_lcd_diagnostic_report,
)


def diagnostic_report(**changes) -> WabbitemuLcdDiagnosticReport:
    values = {
        "boot_steps": 100,
        "boot_tstates": 200,
        "max_probe_steps": 250_000,
        "probe_steps": 10_000,
        "probe_tstates": 20_000,
        **expected_lcd_diagnostic_values(),
    }
    values.update(changes)
    return WabbitemuLcdDiagnosticReport(**values)


class WabbitemuLcdDiagnosticProbeTests(unittest.TestCase):
    def test_native_report_parser_keeps_hashes_and_booleans_typed(self):
        values = diagnostic_report().to_dict()
        values.pop("source_rom_sha256")
        values.pop("binary_sha256")
        fields = " ".join(
            f"{name}={int(value) if isinstance(value, bool) else value}"
            for name, value in values.items()
        )

        report = parse_lcd_diagnostic_report(
            "mode=lcd-diagnostic-probe " + fields
        )

        self.assertTrue(report.completed)
        self.assertEqual(values["fill_hash"], report.fill_hash)

    def test_oracle_validates_actual_rom_helper_effects(self):
        result = validate_lcd_diagnostic_report(diagnostic_report())

        self.assertEqual(24, result["native"]["fill_commands"])
        self.assertEqual(768, result["native"]["fill_data"])
        self.assertEqual(39, result["native"]["contrast_level"])

    def test_oracle_rejects_incomplete_fill(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_lcd_diagnostic_report(diagnostic_report(fill_data=767))

    def test_oracle_rejects_wrong_visible_pattern(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_lcd_diagnostic_report(diagnostic_report(fill_hash=0))


if __name__ == "__main__":
    unittest.main()
