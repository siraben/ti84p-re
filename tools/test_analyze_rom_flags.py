#!/usr/bin/env python3
"""Regression tests for structured indexed-flag scan reports."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_rom_flags import build_parser, report
from rom_image import PAGE_SIZE


class AnalyzeRomFlagsTests(unittest.TestCase):
    def setUp(self):
        self.parser = build_parser()

    def test_report_filters_and_serializes_exact_sequence(self):
        data = bytearray(PAGE_SIZE)
        data[0x100:0x104] = bytes.fromhex("FD CB 2C C6")
        data[0x200:0x204] = bytes.fromhex("FD 36 2C 00")
        digest = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.rom"
            path.write_bytes(data)
            args = self.parser.parse_args(
                [
                    "--rom",
                    str(path),
                    "--offset",
                    "0x2c",
                    "--bit",
                    "0",
                    "--index",
                    "iy",
                    "--expect-sha256",
                    digest,
                ]
            )
            result = report(args)

        self.assertEqual(digest, result["rom_sha256"])
        self.assertEqual("00:0100", result["references"][0]["location"])
        self.assertEqual("set", result["references"][0]["operation"])
        self.assertEqual("00:0200", result["references"][1]["location"])
        self.assertEqual(0, result["references"][1]["selected_bit_value"])
        json.dumps(result)

    def test_hash_guard_rejects_another_rom(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.rom"
            path.write_bytes(bytes(PAGE_SIZE))
            args = self.parser.parse_args(
                [
                    "--rom",
                    str(path),
                    "--expect-sha256",
                    "0" * 64,
                ]
            )
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                report(args)


if __name__ == "__main__":
    unittest.main()
