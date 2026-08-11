#!/usr/bin/env python3
"""Regression tests for reusable ROM call-reference reports."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_rom_calls import (
    bjump_reports_for_page,
    call_reports_for_page,
    resolved_direct_target,
)
from rom_image import RomImage, RomLocation
from z80_disassembly import Z80Instruction


def instruction(address: int, data: bytes, text: str) -> Z80Instruction:
    return Z80Instruction(RomLocation(0, address), data, text)


class AnalyzeRomCallsTests(unittest.TestCase):
    def test_direct_report_includes_typed_target_and_context(self):
        rom = RomImage(bytes(0x4000))
        instructions = (
            instruction(0x0100, bytes.fromhex("3E3E"), "ld a,03eh"),
            instruction(0x0102, bytes.fromhex("CDE745"), "call 045e7h"),
            instruction(0x0105, b"\xC9", "ret"),
        )

        reports = call_reports_for_page(
            rom,
            0,
            instructions,
            frozenset((0x45E7,)),
            bcall=False,
            before=1,
            after=1,
        )

        self.assertEqual(1, len(reports))
        report = reports[0]
        self.assertEqual("direct", report["kind"])
        self.assertEqual(0x45E7, report["target"])
        self.assertEqual("banked:45E7", report["resolved_target"])
        self.assertEqual("00:0102", report["location"])
        self.assertEqual([False, True, False], [item["match"] for item in report["context"]])
        self.assertEqual("3e3e", report["context"][0]["bytes"])

    def test_bcall_report_keeps_complete_raw_sequence(self):
        page = bytearray(0x4000)
        page[0x0102:0x0105] = bytes.fromhex("EF2480")
        rom = RomImage(bytes(page))
        instructions = (
            instruction(0x0102, b"\xEF", "rst 28h"),
            instruction(0x0103, b"\x24", "inc h"),
            instruction(0x0104, b"\x80", "add a,b"),
        )

        reports = call_reports_for_page(
            rom,
            0,
            instructions,
            frozenset((0x8024,)),
            bcall=True,
            before=0,
            after=2,
        )

        self.assertEqual(1, len(reports))
        report = reports[0]
        self.assertEqual("bcall", report["kind"])
        self.assertEqual(0x8024, report["target"])
        self.assertIsNone(report["resolved_target"])
        self.assertEqual("ef2480", report["bytes"])
        self.assertEqual([True, False, False], [item["match"] for item in report["context"]])

    def test_bjump_report_masks_page_and_keeps_raw_descriptor(self):
        page = bytearray(0x4000)
        page[0x0100:0x0106] = bytes.fromhex("CD092B98607D")
        rom = RomImage(bytes(page))
        instructions = (
            instruction(0x0100, bytes.fromhex("CD092B"), "call 02b09h"),
            instruction(0x0103, b"\x98", "sbc a,b"),
        )

        reports = bjump_reports_for_page(
            rom,
            0,
            instructions,
            frozenset((RomLocation(0x3D, 0x6098),)),
            before=0,
            after=1,
        )

        self.assertEqual(1, len(reports))
        report = reports[0]
        self.assertEqual("bjump", report["kind"])
        self.assertEqual("3D:6098", report["target"])
        self.assertEqual(0x7D, report["raw_page"])
        self.assertEqual("cd092b98607d", report["bytes"])

    def test_direct_target_resolution_keeps_banked_page_identity(self):
        self.assertEqual("00:2799", resolved_direct_target(0x3C, 0x2799))
        self.assertEqual("3C:618D", resolved_direct_target(0x3C, 0x618D))
        self.assertEqual("05:618D", resolved_direct_target(0x05, 0x618D))
        self.assertEqual("ram:8100", resolved_direct_target(0x3C, 0x8100))


if __name__ == "__main__":
    unittest.main()
