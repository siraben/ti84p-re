#!/usr/bin/env python3
"""Regression tests for the mapper comparison CLI's structured reports."""

import json
import unittest


from ti84re.hardware.describe_memory_mapping import build_parser, report


class DescribeMemoryMappingTests(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()

    def test_compare_exposes_even_page_difference(self):
        args = self.parser.parse_args(
            ["compare", "--write", "4=1", "--write", "6=2"]
        )

        mappings = report(args)["mappings"]

        self.assertEqual(["tilem", "wabbitemu", "mame"], [m["profile"] for m in mappings])
        self.assertEqual(3, mappings[0]["windows"][2]["page"])
        self.assertEqual(2, mappings[1]["windows"][2]["page"])
        self.assertEqual(3, mappings[2]["windows"][2]["page"])

    def test_mame_report_records_ignored_port_and_read_latch(self):
        args = self.parser.parse_args(
            [
                "map",
                "--profile",
                "mame",
                "--write",
                "0x0e=3",
                "--read",
                "0x4000",
            ]
        )

        mapping = report(args)["mappings"][0]

        self.assertEqual([{"port": 0x0E, "value": 3}], mapping["ignored_writes"])
        self.assertEqual(0, mapping["fixed_page"])
        self.assertFalse(mapping["boot_latch"])
        self.assertEqual(["flash", 0], list(mapping["accesses"][0]["mapping"]))

    def test_reduced_ram_report_separates_selectors_from_physical_backing(self):
        args = self.parser.parse_args(
            [
                "compare",
                "--ram-alias-from",
                "2",
                "--write",
                "4=0",
                "--write",
                "5=7",
                "--write",
                "6=0x87",
                "--write",
                "7=0x87",
            ]
        )

        mappings = report(args)["mappings"]
        wabbitemu = mappings[1]
        mame = mappings[2]

        self.assertEqual(2, wabbitemu["ram_alias_from"])
        self.assertEqual(
            [0x87, 0x87, 7],
            [
                wabbitemu["registers"][index]["readback"]
                for index in (2, 3, 1)
            ],
        )
        self.assertEqual(
            [0x82, 0x82, 0x82],
            [window["page"] for window in wabbitemu["windows"][1:]],
        )
        self.assertEqual(
            [None, None, None],
            [window["page"] for window in mame["windows"][1:]],
        )

    def test_profile_report_is_json_serializable(self):
        args = self.parser.parse_args(["profiles"])

        encoded = json.dumps(report(args))

        self.assertIn("mame0287", encoded)


if __name__ == "__main__":
    unittest.main()
