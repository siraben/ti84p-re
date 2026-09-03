#!/usr/bin/env python3
"""Regression tests for structured LCD-controller CLI reports."""

import json
import unittest


from ti84re.hardware.describe_lcd_controller import build_parser, report


class DescribeLcdControllerTests(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()

    def test_hardware_report_preserves_identification_limit(self):
        controller = report(self.parser.parse_args(["hardware"]))["controller"]

        self.assertEqual("T6K04", controller["part"])
        self.assertEqual(128, controller["columns"])
        self.assertIn("epoxy", controller["identification_limit"])
        self.assertEqual(1000, controller["bus_timings"][0]["enable_cycle_min_ns"])
        json.dumps(controller)

    def test_default_busy_report_covers_four_data_sheet_choices(self):
        intervals = report(self.parser.parse_args(["busy"]))["intervals"]

        self.assertEqual(
            [28.56, 57.12, 228.48, 456.96],
            [interval["oscillator_khz"] for interval in intervals],
        )
        self.assertAlmostEqual(4000 / 28.56, intervals[0]["maximum_us"])
        self.assertAlmostEqual(2000 / 456.96, intervals[-1]["minimum_us"])


if __name__ == "__main__":
    unittest.main()
