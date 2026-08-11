#!/usr/bin/env python3
"""Regression tests for structured link-port CLI reports."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from describe_link_port import build_parser, result


class DescribeLinkPortTests(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()

    def test_compare_exposes_mame_connector_difference(self):
        args = self.parser.parse_args(["compare", "1", "2"])

        implementations = result(args)["implementations"]

        self.assertEqual(
            ["tilem", "wabbitemu", "mame"],
            [row["profile"] for row in implementations],
        )
        self.assertEqual(1, implementations[0]["writes"][0]["connector_drive"])
        self.assertEqual(1, implementations[1]["writes"][0]["connector_drive"])
        self.assertEqual(0, implementations[2]["writes"][0]["connector_drive"])

    def test_mame_special_values_reach_connector_bit_pairs(self):
        args = self.parser.parse_args(["emulator", "mame", "0x14", "0x28"])

        writes = result(args)["implementations"][0]["writes"]

        self.assertEqual([1, 2], [row["connector_drive"] for row in writes])

    def test_profiles_report_is_json_serializable(self):
        args = self.parser.parse_args(["profiles"])

        encoded = json.dumps(result(args))

        self.assertIn("MACHINE_NOT_WORKING", encoded)


if __name__ == "__main__":
    unittest.main()
