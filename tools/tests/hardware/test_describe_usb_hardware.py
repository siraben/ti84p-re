#!/usr/bin/env python3
"""Regression tests for structured USB-hardware CLI reports."""

import json
import unittest


from ti84re.hardware.describe_usb import build_parser, report


class DescribeUsbHardwareTests(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()

    def test_layout_report_separates_sources_and_candidate_maps(self):
        data = report(self.parser.parse_args(["layouts"]))
        rows = {row["port"]: row for row in data["registers"]}

        self.assertEqual(3, len(data["sources"]))
        self.assertEqual(("INTRUSB",), rows[0x86]["fdrc_names"])
        self.assertEqual(("INTRTX1E",), rows[0x86]["hdrc_names"])
        self.assertFalse(rows[0x8F]["same_names"])
        json.dumps(data)

    def test_register_report_keeps_ti_identity_hypothetical(self):
        register = report(self.parser.parse_args(["register", "0x86"]))["registers"][0]

        self.assertTrue(register["mapped"])
        self.assertIn("hypothesis", register["evidence"])

    def test_unobserved_low_usb_ports_are_absent_from_all_profiles(self):
        data = report(self.parser.parse_args(["reads", "0x49", "0x51", "0x52"]))

        self.assertEqual(9, len(data["reads"]))
        self.assertTrue(all(not row["modeled"] for row in data["reads"]))


if __name__ == "__main__":
    unittest.main()
