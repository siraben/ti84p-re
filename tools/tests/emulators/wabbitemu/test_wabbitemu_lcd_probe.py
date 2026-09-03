#!/usr/bin/env python3
"""Regression tests for the reusable native Wabbitemu LCD oracle."""

import unittest

from ti84re.emulators.wabbitemu.headless import WabbitemuHeadlessError, WabbitemuLcdReport
from ti84re.emulators.wabbitemu.lcd_probe import expected_lcd_values, validate_lcd_report


def lcd_report(**changes) -> WabbitemuLcdReport:
    values = expected_lcd_values()
    values.update(changes)
    return WabbitemuLcdReport(**values)


class WabbitemuLcdProbeTests(unittest.TestCase):
    def test_oracle_validates_controller_and_bus_edges(self):
        result = validate_lcd_report(lcd_report())

        self.assertEqual(0x23, result["native"]["boundary_status"])
        self.assertEqual((0, 0x12, 0x34), result["native"]["latch_reads"])
        self.assertEqual(240, result["native"]["ready_hold"])
        self.assertEqual(9, result["native"]["delay_after"] - 3000)
        self.assertEqual(1, result["native"]["clamped_speed"])

    def test_oracle_rejects_documented_column_increment(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_lcd_report(lcd_report(wrap_column15=0xA1))

    def test_oracle_rejects_read_timestamp_restart(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_lcd_report(lcd_report(ready_after_read_last_tstate=2241))


if __name__ == "__main__":
    unittest.main()
