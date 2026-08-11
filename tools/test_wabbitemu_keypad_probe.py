#!/usr/bin/env python3
"""Regression tests for the reusable native Wabbitemu keypad oracle."""

import unittest

from wabbitemu_headless import WabbitemuHeadlessError, WabbitemuKeypadReport
from wabbitemu_keypad_probe import expected_keypad_values, validate_keypad_report


def keypad_report(**changes) -> WabbitemuKeypadReport:
    values = expected_keypad_values()
    values.update(changes)
    return WabbitemuKeypadReport(**values)


class WabbitemuKeypadProbeTests(unittest.TestCase):
    def test_oracle_validates_pairwise_matrix_and_press_edge(self):
        result = validate_keypad_report(keypad_report())

        self.assertEqual(7, result["source_model"]["matrix_groups"])
        self.assertEqual(0xFC, result["native"]["transitive_read"])
        self.assertEqual(0x01, result["native"]["on_press_after_eval"])

    def test_oracle_rejects_transitive_closure(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_keypad_report(keypad_report(transitive_read=0xF8))

    def test_oracle_rejects_release_edge_latch(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_keypad_report(keypad_report(on_release_after_eval=0x09))


if __name__ == "__main__":
    unittest.main()
