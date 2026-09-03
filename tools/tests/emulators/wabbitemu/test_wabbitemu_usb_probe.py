#!/usr/bin/env python3
"""Regression tests for the reusable native Wabbitemu USB oracle."""

import unittest

from ti84re.emulators.wabbitemu.headless import WabbitemuHeadlessError, WabbitemuUsbReport
from ti84re.emulators.wabbitemu.usb_probe import expected_usb_values, validate_usb_report


def usb_report(**changes) -> WabbitemuUsbReport:
    values = expected_usb_values()
    values.update(changes)
    return WabbitemuUsbReport(**values)


class WabbitemuUsbProbeTests(unittest.TestCase):
    def test_oracle_validates_registration_events_and_latches(self):
        result = validate_usb_report(usb_report())

        self.assertFalse(result["native"]["port54_active"])
        self.assertEqual(0xE5, result["native"]["event_line_state"])
        self.assertEqual(0x58, result["native"]["event_events"])
        self.assertEqual(0x1B, result["native"]["event_port55"])
        self.assertTrue(result["native"]["repeated_event_interrupt"])

    def test_oracle_rejects_mask_gating_not_present_in_source(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_usb_report(usb_report(event_interrupt=False))

    def test_oracle_rejects_non_runtime_port54_registration(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_usb_report(usb_report(port54_active=True))


if __name__ == "__main__":
    unittest.main()
