#!/usr/bin/env python3
"""Regression tests for the reusable native Wabbitemu MD5 oracle."""

import unittest

from wabbitemu_headless import WabbitemuHeadlessError, WabbitemuMd5EdgeReport
from wabbitemu_md5_probe import expected_md5_edge_values, validate_md5_edge_report


def edge_report(**changes) -> WabbitemuMd5EdgeReport:
    values = expected_md5_edge_values()
    values.update(changes)
    return WabbitemuMd5EdgeReport(**values)


class WabbitemuMd5ProbeTests(unittest.TestCase):
    def test_oracle_validates_sliding_controls_and_mixed_read(self):
        result = validate_md5_edge_report(edge_report())

        self.assertEqual(0x1F, result["source_model"]["shift_mask"])
        self.assertEqual(0x343F97B4, result["native"]["mixed_result"])

    def test_oracle_rejects_latched_result(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_md5_edge_report(
                edge_report(mixed_result=0xD6D117B4)
            )


if __name__ == "__main__":
    unittest.main()
