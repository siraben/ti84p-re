#!/usr/bin/env python3
"""Regression tests for the reusable native Wabbitemu interrupt oracle."""

import unittest

from wabbitemu_headless import WabbitemuHeadlessError, WabbitemuInterruptReport
from wabbitemu_interrupt_probe import (
    expected_interrupt_values,
    validate_interrupt_report,
)


def interrupt_report(**changes) -> WabbitemuInterruptReport:
    values = expected_interrupt_values()
    values.update(changes)
    return WabbitemuInterruptReport(**values)


class WabbitemuInterruptProbeTests(unittest.TestCase):
    def test_oracle_validates_interrupt_and_low_power_edges(self):
        result = validate_interrupt_report(interrupt_report())

        self.assertEqual(4_405_286, result["native"]["rate1_timer1_ns"])
        self.assertEqual(0x08, result["native"]["after_port3_ack_status"])
        self.assertEqual(0xE8, result["native"]["completion_status"])
        self.assertTrue(result["native"]["restored_lcd_active"])

    def test_oracle_rejects_inclusive_timer_boundary(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_interrupt_report(
                interrupt_report(exact_boundary_interrupt=True)
            )

    def test_oracle_rejects_stale_timer_after_port3_ack(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_interrupt_report(
                interrupt_report(after_port3_ack_status=0x0A)
            )


if __name__ == "__main__":
    unittest.main()
