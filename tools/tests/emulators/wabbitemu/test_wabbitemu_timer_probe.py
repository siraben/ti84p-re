#!/usr/bin/env python3
"""Regression tests for the reusable native Wabbitemu timer oracle."""

import unittest

from ti84re.emulators.wabbitemu.headless import WabbitemuHeadlessError, WabbitemuTimerReport
from ti84re.emulators.wabbitemu.timer_probe import expected_timer_values, validate_timer_report


def timer_report(**changes) -> WabbitemuTimerReport:
    values = expected_timer_values()
    values.update(changes)
    return WabbitemuTimerReport(**values)


class WabbitemuTimerProbeTests(unittest.TestCase):
    def test_oracle_validates_catch_up_halt_and_rtc_edges(self):
        result = validate_timer_report(timer_report())

        self.assertEqual((2, 1, 3), result["native"]["crystal_reads"])
        self.assertEqual(4, result["native"]["zero_status"])
        self.assertTrue(result["native"]["interrupt_after_resume"])
        self.assertEqual(0x12345682, result["native"]["rtc_late_disabled"])

    def test_oracle_rejects_documented_crystal_divisor(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_timer_report(timer_report(crystal_divisor=33))

    def test_oracle_rejects_zero_without_underflow(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_timer_report(timer_report(zero_status=0))


if __name__ == "__main__":
    unittest.main()
