#!/usr/bin/env python3
"""Regression tests for the reusable native Wabbitemu mapper oracle."""

import unittest

from wabbitemu_headless import WabbitemuHeadlessError, WabbitemuMapperReport
from wabbitemu_mapper_probe import expected_mapper_values, validate_mapper_report


def mapper_report(**changes) -> WabbitemuMapperReport:
    values = expected_mapper_values()
    values.update(changes)
    return WabbitemuMapperReport(**values)


class WabbitemuMapperProbeTests(unittest.TestCase):
    def test_oracle_validates_handoff_pairing_and_overlays(self):
        result = validate_mapper_report(mapper_report())

        self.assertEqual(0x3F, result["native"]["fixed_page_after_data_read"])
        self.assertEqual(0, result["native"]["fixed_page_after_opcode"])
        self.assertEqual((2, 2, 3), (
            result["native"]["paired_a_page"],
            result["native"]["paired_b_page"],
            result["native"]["paired_c_page"],
        ))
        self.assertFalse(result["native"]["independent_fetch_halted"])
        self.assertTrue(result["native"]["paired_fetch_halted"])

    def test_oracle_rejects_adjacent_odd_paired_page(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_mapper_report(mapper_report(paired_b_page=3))

    def test_oracle_rejects_overlay_in_paired_mode(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_mapper_report(mapper_report(paired_8000=0xB0))


if __name__ == "__main__":
    unittest.main()
