#!/usr/bin/env python3
"""Regression tests for raw indexed-bit ROM scans."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from indexed_flags import (
    normalize_displacement,
    scan_indexed_bit_references,
    scan_indexed_immediate_writes,
)
from rom_image import PAGE_SIZE, RomImage, RomLocation


class IndexedFlagsTests(unittest.TestCase):
    def setUp(self):
        data = bytearray(2 * PAGE_SIZE)
        data[0x0100:0x0104] = bytes.fromhex("FD CB 2C 46")
        data[0x0200:0x0204] = bytes.fromhex("DD CB FE 9E")
        data[PAGE_SIZE + 0x0300 : PAGE_SIZE + 0x0304] = bytes.fromhex("FD CB 2C C6")
        data[PAGE_SIZE + 0x0400 : PAGE_SIZE + 0x0404] = bytes.fromhex("FD CB 2C C0")
        data[PAGE_SIZE + 0x0500 : PAGE_SIZE + 0x0504] = bytes.fromhex("FD 36 2C 00")
        self.rom = RomImage(bytes(data))

    def test_scans_pages_and_decodes_operations(self):
        references = scan_indexed_bit_references(self.rom)

        self.assertEqual(3, len(references))
        self.assertEqual(RomLocation(0, 0x0100), references[0].location)
        self.assertEqual(
            ("iy", 0x2C, "bit", 0),
            (
                references[0].index_register,
                references[0].displacement,
                references[0].operation,
                references[0].bit,
            ),
        )
        self.assertEqual(
            ("ix", -2, "res", 3),
            (
                references[1].index_register,
                references[1].displacement,
                references[1].operation,
                references[1].bit,
            ),
        )
        self.assertEqual(RomLocation(1, 0x4300), references[2].location)
        self.assertEqual("set", references[2].operation)

    def test_filters_by_register_displacement_bit_and_page(self):
        references = scan_indexed_bit_references(
            self.rom,
            index_register="IY",
            displacement=0x2C,
            bit=0,
            pages=(1,),
        )

        self.assertEqual(
            (RomLocation(1, 0x4300),),
            tuple(reference.location for reference in references),
        )

    def test_ignores_indexed_copy_to_register_opcode(self):
        references = scan_indexed_bit_references(self.rom, pages=(1,))

        self.assertEqual(1, len(references))

    def test_scans_indexed_immediate_flag_byte_write(self):
        writes = scan_indexed_immediate_writes(
            self.rom,
            displacement=0x2C,
            index_register="iy",
        )

        self.assertEqual(1, len(writes))
        self.assertEqual(RomLocation(1, 0x4500), writes[0].location)
        self.assertEqual(0, writes[0].value)

    def test_normalizes_raw_and_signed_displacements(self):
        self.assertEqual(-2, normalize_displacement(0xFE))
        self.assertEqual(-2, normalize_displacement(-2))
        with self.assertRaises(ValueError):
            normalize_displacement(0x100)

    def test_rejects_invalid_filters(self):
        with self.assertRaises(ValueError):
            scan_indexed_bit_references(self.rom, bit=8)
        with self.assertRaises(ValueError):
            scan_indexed_bit_references(self.rom, index_register="hl")
        with self.assertRaises(ValueError):
            scan_indexed_bit_references(self.rom, pages=(2,))


if __name__ == "__main__":
    unittest.main()
