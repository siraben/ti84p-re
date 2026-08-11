#!/usr/bin/env python3
"""Regression tests for structured Flash-worker comparison reports."""

import json
import unittest

from describe_flash_workers import report
from rom_image import RomImage, RomLocation


class DescribeFlashWorkersTests(unittest.TestCase):
    def test_report_serializes_worker_metadata_and_differences(self):
        data = bytearray(0x4000)
        data[0x100:0x105] = bytes.fromhex("0300aabbcc")
        data[0x200:0x206] = bytes.fromhex("0400aa11bbcc")

        result = report(
            RomImage(bytes(data)),
            RomLocation(0, 0x4100),
            RomLocation(0, 0x4200),
        )

        self.assertEqual(3, result["left"]["length"])
        self.assertEqual(4, result["right"]["length"])
        self.assertEqual(3, result["matching_bytes"])
        self.assertEqual("11", result["differences"][0]["right_bytes"])
        json.dumps(result)


if __name__ == "__main__":
    unittest.main()
