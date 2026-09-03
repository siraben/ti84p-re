#!/usr/bin/env python3
"""Regression tests for bus-timing implementation reports."""

import json
import unittest


from ti84re.hardware.describe_bus_timing import build_parser, report


class DescribeBusTimingTests(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()

    def test_compare_reports_mame_delay_port_omissions(self):
        result = report(self.parser.parse_args(["--compare"]))

        implementations = result["implementations"]
        self.assertEqual(
            ["tilem", "wabbitemu", "mame"],
            [implementation["profile"] for implementation in implementations],
        )
        mame = implementations[2]
        self.assertFalse(mame["delay_registers"])
        self.assertEqual([], mame["modes"])
        self.assertEqual(
            [0x29, 0x2A, 0x2B, 0x2C, 0x2E, 0x2F],
            [write["port"] for write in mame["ignored_writes"]],
        )

    def test_wabbitemu_extra_speeds_are_explicit(self):
        args = self.parser.parse_args(
            [
                "--profile",
                "wabbitemu",
                "--extra-speeds",
                "--write",
                "0x20=3",
            ]
        )

        implementation = report(args)["implementations"][0]

        self.assertTrue(implementation["extra_speeds"])
        self.assertEqual(3, implementation["current_speed_mode"])
        self.assertEqual(25, implementation["clock_mhz"])

    def test_report_is_json_serializable(self):
        result = report(self.parser.parse_args(["--compare"]))

        encoded = json.dumps(result)

        self.assertIn("mame0287", encoded)


if __name__ == "__main__":
    unittest.main()
