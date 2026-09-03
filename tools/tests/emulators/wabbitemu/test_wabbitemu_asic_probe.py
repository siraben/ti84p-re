#!/usr/bin/env python3
"""Regression tests for the reusable native Wabbitemu ASIC oracle."""

import unittest

from ti84re.emulators.wabbitemu.asic_probe import expected_asic_values, validate_asic_report
from ti84re.emulators.wabbitemu.headless import WabbitemuAsicReport, WabbitemuHeadlessError


def asic_report(**changes) -> WabbitemuAsicReport:
    values = expected_asic_values()
    values.update(changes)
    return WabbitemuAsicReport(**values)


class WabbitemuAsicProbeTests(unittest.TestCase):
    def test_oracle_validates_status_protection_and_gpio_edges(self):
        result = validate_asic_report(asic_report())

        self.assertEqual(0xE7, result["native"]["port02_unlocked"])
        self.assertEqual(3, result["native"]["mode3_internal_mode"])
        self.assertEqual(0, result["native"]["mode3_read"])
        self.assertFalse(result["native"]["port39_active"])
        self.assertEqual(0x5A, result["native"]["port3a_second_read"])

    def test_oracle_rejects_visible_ram_mode(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_asic_report(asic_report(mode3_read=0x30))

    def test_oracle_rejects_unprotected_write(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_asic_report(asic_report(locked_write_accepted=True))


if __name__ == "__main__":
    unittest.main()
