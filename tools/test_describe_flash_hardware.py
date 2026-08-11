#!/usr/bin/env python3
"""Regression tests for structured Flash-device CLI reports."""

import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from describe_flash_hardware import build_parser, report


class DescribeFlashHardwareTests(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()

    def test_parts_separate_photographed_part_from_reported_families(self):
        data = report(self.parser.parse_args(["parts"]))

        self.assertEqual(
            "MBM29LV800TA-70PFTN",
            data["photographed_part"]["orderable_part"],
        )
        self.assertEqual(0x04, data["photographed_part"]["manufacturer_code"])
        self.assertEqual(
            ["A29L800A", "29LV800", "S29AL008D", "MX29LV800"],
            [part["family"] for part in data["reported_compatible_parts"]],
        )
        json.dumps(data)

    def test_profiles_expose_numeric_emulator_autoselect_ids(self):
        profiles = report(self.parser.parse_args(["profiles"]))["profiles"]

        self.assertIsNone(profiles[0]["autoselect_manufacturer_code"])
        self.assertEqual(
            [(0x01, 0xDA), (0x01, 0xDA)],
            [
                (
                    profile["autoselect_manufacturer_code"],
                    profile["autoselect_device_code"],
                )
                for profile in profiles[1:]
            ],
        )

    def test_commands_expose_nested_support_and_serialize(self):
        data = report(self.parser.parse_args(["commands"]))
        profiles = data["command_profiles"]

        self.assertEqual("Fujitsu MBM29LV800TA", profiles[0]["name"])
        self.assertEqual("defined", profiles[0]["erase_suspend_resume"]["status"])
        self.assertEqual("partial", profiles[1]["fast_program"]["status"])
        json.dumps(data)


if __name__ == "__main__":
    unittest.main()
