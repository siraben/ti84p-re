#!/usr/bin/env python3
"""Regression tests for structured link-port CLI reports."""

import json
import unittest


from ti84re.link.describe_port import build_parser, result


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

    def test_keyboard_cli_reports_consumed_data_not_a_returned_scan_code(self):
        args = self.parser.parse_args(
            [
                "keyboard",
                "--prefix",
                "0xE0",
                "--delimiter-error",
                "--command",
                "0x01",
                "--data",
                "0x42",
            ]
        )

        report = result(args)

        self.assertEqual(0x01, report["status"])
        self.assertEqual(0x42, report["data"])
        self.assertTrue(report["data_consumed"])
        self.assertFalse(report["data_returned"])

    def test_keyboard_path_cli_exposes_assist_error_tail(self):
        args = self.parser.parse_args(
            [
                "keyboard-path",
                "--assist-status",
                "0x50",
                "--buffered",
                "0xE0",
            ]
        )

        report = result(args)

        self.assertEqual(0xFB, report["status"])
        self.assertEqual("3C:6D87", report["return_address"])

    def test_keyboard_rom_cli_reports_verified_target(self):
        args = self.parser.parse_args(["keyboard-rom"])

        report = result(args)

        self.assertEqual("3C:6D5E", report["target"])
        self.assertEqual(3, len(report["regions"]))


if __name__ == "__main__":
    unittest.main()
