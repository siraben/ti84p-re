#!/usr/bin/env python3
"""Regression tests for reusable ROM and bcall-table parsing."""

import unittest
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bcall_tables import (
    RETAIL_PAGE3F_PREFIX,
    boot_target,
    classify_boot_page,
    find_main_table_page,
    iter_bjump_targets,
    main_target,
    read_equate_names,
)
from rom_image import PAGE_SIZE, RomFormatError, RomImage


class RomImageTests(unittest.TestCase):
    def test_maps_banked_logical_address_to_page_offset(self):
        data = bytearray(2 * PAGE_SIZE)
        data[PAGE_SIZE + 0x123] = 0xA5
        rom = RomImage(bytes(data))

        self.assertEqual(b"\xA5", rom.bytes_at(1, 0x4123, 1))
        self.assertEqual(PAGE_SIZE + 0x123, rom.flat_offset(1, 0x4123))

    def test_rejects_cross_page_read(self):
        rom = RomImage(bytes(PAGE_SIZE))

        with self.assertRaisesRegex(RomFormatError, "crosses"):
            rom.bytes_at(0, 0x7FFF, 2)


class BcallTableTests(unittest.TestCase):
    def setUp(self):
        data = bytearray(64 * PAGE_SIZE)
        data[0x3F * PAGE_SIZE : 0x3F * PAGE_SIZE + len(RETAIL_PAGE3F_PREFIX)] = (
            RETAIL_PAGE3F_PREFIX
        )
        main_offset = 0x3B * PAGE_SIZE + 0x123
        data[main_offset : main_offset + 3] = bytes.fromhex("67 45 7F")
        boot_offset = 0x3F * PAGE_SIZE + 0x10B
        data[boot_offset : boot_offset + 3] = bytes.fromhex("C5 62 2F")
        data[0x3B01 : 0x3B07] = bytes.fromhex("CD 09 2B 80 42 75")
        self.rom = RomImage(bytes(data))

    def test_resolves_main_entry_and_masks_raw_page(self):
        target = main_target(self.rom, 0x3B, 0x4123, "_Example")

        self.assertEqual(0x4567, target.address)
        self.assertEqual(0x3F, target.page)
        self.assertEqual("3F:4567", str(target.location))

    def test_finds_main_table_page_by_valid_entries(self):
        self.assertEqual((0x3B, 1), find_main_table_page(self.rom, [0x4123]))

    def test_resolves_unnamed_boot_entry(self):
        target = boot_target(self.rom, 0x810B)

        self.assertIsNotNone(target)
        self.assertEqual(0x62C5, target.address)
        self.assertEqual(0x2F, target.page)
        self.assertIsNone(target.name)

    def test_rejects_dispatch_stub_bytes_as_boot_entries(self):
        for identifier in range(0x80D5, 0x80E2, 3):
            with self.subTest(identifier=identifier):
                self.assertIsNone(boot_target(self.rom, identifier))

    def test_rejects_unaligned_boot_ids(self):
        for identifier in (0x8019, 0x80D1, 0x80E5, 0x8128):
            with self.subTest(identifier=identifier):
                self.assertIsNone(boot_target(self.rom, identifier))

    def test_classifies_retail_boot_page(self):
        self.assertEqual("retail", classify_boot_page(self.rom))

    def test_decodes_bjump_descriptor(self):
        target = list(iter_bjump_targets(self.rom))[0]

        self.assertEqual(0x3B01, target.trampoline)
        self.assertEqual(0x4280, target.address)
        self.assertEqual(0x35, target.page)

    def test_reads_public_equate_names_in_requested_range(self):
        with tempfile.TemporaryDirectory() as directory:
            include = Path(directory) / "example.inc"
            include.write_text(
                "_Outside equ 1234h\n_SendUSBData equ 50F2h\n", encoding="ascii"
            )

            self.assertEqual(
                {0x50F2: "_SendUSBData"},
                read_equate_names(include, 0x4000, 0x7FFF),
            )


if __name__ == "__main__":
    unittest.main()
