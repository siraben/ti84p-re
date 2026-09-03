#!/usr/bin/env python3
"""Regression tests for the reusable native Wabbitemu speed oracle."""

import unittest

from ti84re.emulators.wabbitemu.headless import WabbitemuHeadlessError, WabbitemuSpeedReport
from ti84re.emulators.wabbitemu.speed_probe import expected_speed_values, validate_speed_report


def speed_report(**changes) -> WabbitemuSpeedReport:
    values = expected_speed_values()
    values.update(changes)
    return WabbitemuSpeedReport(**values)


class WabbitemuSpeedProbeTests(unittest.TestCase):
    def test_oracle_validates_speed_latches_and_waits(self):
        result = validate_speed_report(speed_report())

        self.assertEqual((0, 1, 1, 1), result["native"]["default_speed_reads"])
        self.assertEqual((0, 1, 2, 3), result["native"]["extra_speed_reads"])
        self.assertEqual((0x00, 0x07, 0x38, 0x3F), result["native"]["wait_masks"])
        self.assertEqual(0x5A, result["native"]["port2d_read"])

    def test_oracle_rejects_unclamped_default_speed(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_speed_report(speed_report(default_speed_reads=(0, 1, 2, 1)))

    def test_oracle_rejects_port2d_timer_side_effect(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_speed_report(speed_report(port2d_xtal_unchanged=False))


if __name__ == "__main__":
    unittest.main()
