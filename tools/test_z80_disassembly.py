#!/usr/bin/env python3
"""Regression tests for reusable z80dasm parsing and literal searches."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from z80_disassembly import (
    direct_target,
    find_bcall_sites,
    find_literal_uses,
    nearby_direct_sinks,
    parse_z80dasm,
)
from rom_image import RomImage


SAMPLE = """\
\tld a,022h\t\t;5dc8\t3e 22\t\t> \"
\tld (0867fh),a\t\t;5dca\t32 7f 86\t2 . .
\tjp nz,02799h\t\t;5dcd\tc2 99 27\t. . '
"""


class Z80DisassemblyTests(unittest.TestCase):
    def setUp(self):
        self.instructions = tuple(parse_z80dasm(SAMPLE, 0x3C))

    def test_parser_keeps_location_bytes_and_text(self):
        instruction = self.instructions[0]

        self.assertEqual("3C:5DC8", str(instruction.location))
        self.assertEqual(bytes.fromhex("3E22"), instruction.data)
        self.assertEqual("ld a,022h", instruction.text)

    def test_literal_search_uses_operands(self):
        uses = tuple(find_literal_uses(self.instructions, (0x22, 0x23)))

        self.assertEqual(1, len(uses))
        self.assertEqual((0x22,), uses[0].values)

    def test_direct_target_accepts_conditional_jump(self):
        self.assertEqual(0x2799, direct_target(self.instructions[2]))

    def test_nearby_sink_is_only_a_proximity_result(self):
        sinks = nearby_direct_sinks(
            self.instructions, 0, (0x2793, 0x2799), distance=2
        )

        self.assertEqual((self.instructions[2],), sinks)

    def test_bcall_search_uses_rst28_and_little_endian_id(self):
        page = bytearray(0x4000)
        page[0x123:0x126] = bytes.fromhex("EFD744")
        rom = RomImage(bytes(page))

        sites = tuple(find_bcall_sites(rom, 0, (0x44D7,)))

        self.assertEqual(1, len(sites))
        self.assertEqual("00:0123", str(sites[0].location))
        self.assertEqual(0x44D7, sites[0].id)


if __name__ == "__main__":
    unittest.main()
