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

    def test_wabbitemu_poll_reports_one_pair_as_json_data(self):
        data = report(
            self.parser.parse_args(
                [
                    "wabbitemu-poll",
                    "--old",
                    "0x50",
                    "--data",
                    "0xD0",
                    "--json",
                ]
            )
        )
        poll = data["wabbitemu_poll"]

        self.assertEqual("stalled", poll["outcome"])
        self.assertEqual(2, poll["repeat_loop_index"])
        self.assertEqual(
            [0x20, 0x50, 0x50, 0x50], [read["value"] for read in poll["reads"]]
        )
        json.dumps(data)

    def test_wabbitemu_poll_without_pair_reports_exhaustive_summary(self):
        data = report(self.parser.parse_args(["wabbitemu-poll"]))
        summary = data["wabbitemu_summary"]

        self.assertEqual(49152, summary["successes"])
        self.assertEqual(4096, summary["failures"])
        self.assertEqual(12288, summary["stalled"])


if __name__ == "__main__":
    unittest.main()
