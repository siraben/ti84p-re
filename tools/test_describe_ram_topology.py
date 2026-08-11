"""Regression tests for the RAM-topology debugging CLI."""

import json
import unittest

from describe_ram_topology import build_parser, report


class DescribeRamTopologyTests(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()

    def test_decode_accepts_delimited_bytes(self):
        result = report(
            self.parser.parse_args(["--observed", "22,22,44,44,55,66"])
        )

        self.assertEqual("partial-selector-aliases", result["topology_observation"])

    def test_simulation_exposes_shared_backing(self):
        result = report(
            self.parser.parse_args(["--simulate-backings", "2,2,2,2,2,2"])
        )

        self.assertEqual("666666666666", result["observed"])
        self.assertEqual("selectors-82-through-87-alias", result["topology_observation"])

    def test_supplied_restore_is_checked_and_json_serializable(self):
        result = report(
            self.parser.parse_args(
                [
                    "--observed",
                    "112233445566",
                    "--original",
                    "102030405060",
                    "--restored",
                    "102030405061",
                ]
            )
        )

        self.assertFalse(result["restore_matches"])
        self.assertIn("independent-selectors", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
