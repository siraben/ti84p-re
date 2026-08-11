#!/usr/bin/env python3
"""Regression tests for the native Wabbitemu protected-port oracle."""

import unittest

from wabbitemu_headless import (
    WabbitemuHeadlessError,
    WabbitemuProtectionPortReport,
)
from wabbitemu_protection_port_probe import (
    expected_protection_port_values,
    validate_protection_port_report,
)


def protection_port_report(**changes) -> WabbitemuProtectionPortReport:
    values = expected_protection_port_values()
    values.update(changes)
    return WabbitemuProtectionPortReport(**values)


class WabbitemuProtectionPortProbeTests(unittest.TestCase):
    def test_oracle_validates_gate_high_bits_and_wrap(self):
        result = validate_protection_port_report(protection_port_report())

        self.assertEqual((False,) * 5, result["native"]["locked_write_accepted"])
        self.assertEqual(0x00CC, result["native"]["port24_flash_lower"])
        self.assertEqual(0x00DD, result["native"]["port24_flash_upper"])
        self.assertEqual(
            (0xFC00, 0x0000, 0x0400, 0xFC00),
            result["native"]["ram_lower_internal"],
        )

    def test_oracle_rejects_port24_high_bit_extension(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_protection_port_report(
                protection_port_report(port24_flash_lower=0x01CC)
            )

    def test_oracle_rejects_wide_ram_storage(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_protection_port_report(
                protection_port_report(
                    ram_upper_internal=(0xFFFF, 0x103FF, 0x107FF, 0x3FFFF)
                )
            )


if __name__ == "__main__":
    unittest.main()
