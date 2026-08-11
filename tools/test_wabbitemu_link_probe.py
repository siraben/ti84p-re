#!/usr/bin/env python3
"""Regression tests for the reusable native Wabbitemu link oracle."""

import unittest

from wabbitemu_headless import WabbitemuHeadlessError, WabbitemuLinkReport
from wabbitemu_link_probe import expected_link_values, validate_link_report


def link_report(**changes) -> WabbitemuLinkReport:
    values = expected_link_values()
    values.update(changes)
    return WabbitemuLinkReport(**values)


class WabbitemuLinkProbeTests(unittest.TestCase):
    def test_oracle_validates_raw_and_assist_edges(self):
        result = validate_link_report(link_report())

        self.assertEqual(0x21, result["native"]["raw_high_write"])
        self.assertEqual(
            (2, 1, 2, 1, 1, 2, 1, 2),
            result["native"]["assist_send_drives"],
        )
        self.assertEqual(0xA5, result["native"]["assist_receive_in"])
        self.assertEqual(0x4C, result["native"]["assist_error_status"])

    def test_oracle_rejects_raw_transition_interrupt(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_link_report(link_report(raw_peer_interrupt=True))

    def test_oracle_rejects_mapped_middle_assist_port(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_link_report(link_report(port0b_active=True))


if __name__ == "__main__":
    unittest.main()
