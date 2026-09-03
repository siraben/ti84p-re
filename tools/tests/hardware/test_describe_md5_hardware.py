#!/usr/bin/env python3
"""Regression tests for MD5-assist implementation reports."""

import json
import unittest


from ti84re.hardware.describe_md5 import build_parser, report


class DescribeMd5HardwareTests(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()

    def test_default_report_compares_three_emulators(self):
        implementations = report(self.parser.parse_args([]))["implementations"]

        self.assertEqual(
            ["tilem", "wabbitemu", "mame"],
            [implementation["key"] for implementation in implementations],
        )
        self.assertEqual(0xD6D117B4, implementations[0]["result"])
        self.assertEqual(0xD6D117B4, implementations[1]["result"])
        self.assertIsNone(implementations[2]["result"])
        self.assertEqual(26, implementations[2]["ignored_write_count"])

    def test_custom_step_is_json_serializable(self):
        args = self.parser.parse_args(
            ["--profile", "tilem", "--mode", "3", "--shift", "0x1f"]
        )

        encoded = json.dumps(report(args))

        self.assertIn('"mode": 3', encoded)
        self.assertIn('"shift": 31', encoded)


if __name__ == "__main__":
    unittest.main()
