#!/usr/bin/env python3
"""Regression tests for static Z80 I/O-access decoding."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rom_image import RomLocation
from z80_disassembly import Z80Instruction
from z80_io import direct_io_access, iter_direct_io_accesses, parse_port_specs


def instruction(address: int, text: str, data: bytes = b"\0") -> Z80Instruction:
    return Z80Instruction(RomLocation(0x35, address), data, text)


class Z80IOTests(unittest.TestCase):
    def test_decodes_immediate_input_port(self):
        access = direct_io_access(instruction(0x4000, "in a,(04dh)"))

        self.assertIsNotNone(access)
        self.assertEqual("in", access.direction)
        self.assertEqual(0x4D, access.port)

    def test_decodes_immediate_output_port(self):
        access = direct_io_access(instruction(0x4000, "out (0a2h),a"))

        self.assertIsNotNone(access)
        self.assertEqual("out", access.direction)
        self.assertEqual(0xA2, access.port)

    def test_rejects_register_indirect_port(self):
        self.assertIsNone(direct_io_access(instruction(0x4000, "outi")))
        self.assertIsNone(direct_io_access(instruction(0x4000, "in a,(c)")))

    def test_filters_selected_ports(self):
        instructions = (
            instruction(0x4000, "in a,(04dh)"),
            instruction(0x4002, "out (055h),a"),
        )

        accesses = tuple(iter_direct_io_accesses(instructions, (0x55,)))

        self.assertEqual(1, len(accesses))
        self.assertEqual(0x55, accesses[0].port)

    def test_parses_ports_and_inclusive_ranges(self):
        self.assertEqual(
            frozenset((0x4D, 0x80, 0x81, 0x82)),
            parse_port_specs(("0x4d", "0x80-0x82")),
        )

    def test_parses_comma_separated_selectors(self):
        self.assertEqual(
            frozenset((0x55, 0x57, 0x58)), parse_port_specs(("0x55,0x57-0x58",))
        )

    def test_rejects_invalid_port_selectors(self):
        for spec in ("0x100", "0x82-0x80", "garbage", "0x80,"):
            with self.subTest(spec=spec):
                with self.assertRaises(ValueError):
                    parse_port_specs((spec,))


if __name__ == "__main__":
    unittest.main()
