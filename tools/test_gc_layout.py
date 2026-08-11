#!/usr/bin/env python3
"""Regression tests for controlled archive-sector layouts."""

from hashlib import sha256
from pathlib import Path
import unittest

from flash_hardware import FLASH_SIZE
from gc_layout import (
    GcLayoutError,
    archive_sector_address,
    build_gc_sector_layout,
)


ROM = Path(__file__).resolve().parent / "rom.bin"


class GcLayoutTests(unittest.TestCase):
    def test_maps_aligned_archive_pages_to_physical_headers(self):
        self.assertEqual(0x20000, archive_sector_address(0x08))
        self.assertEqual(0xA0000, archive_sector_address(0x28))
        with self.assertRaisesRegex(GcLayoutError, "four-page aligned"):
            archive_sector_address(0x09)
        with self.assertRaisesRegex(GcLayoutError, "must be"):
            archive_sector_address(0x2C)

    def test_builds_copy_and_reports_every_mutation(self):
        source = b"\xFF" * FLASH_SIZE
        result = build_gc_sector_layout(source, ((0x08, 0xFE), (0x28, 0xF0)))

        self.assertEqual(0xFF, source[0x20000])
        self.assertEqual(0xFE, result.image[0x20000])
        self.assertEqual(0xF0, result.image[0xA0000])
        self.assertEqual((0x08, 0x28), tuple(item.page for item in result.mutations))
        self.assertEqual((0xFF, 0xFF), tuple(item.previous for item in result.mutations))

    def test_reconstructs_phase_fc_fixture_identity(self):
        result = build_gc_sector_layout(
            ROM.read_bytes(), ((0x08, 0xFE), (0x28, 0xF0))
        )

        self.assertEqual(
            "788b3c088e2954be5e53689afa7ac07d80159086a45d213a53f88952a65dd2e1",
            sha256(result.image).hexdigest(),
        )

    def test_rejects_non_erased_duplicate_or_unknown_headers(self):
        source = bytearray(b"\xFF" * FLASH_SIZE)
        source[0x20000] = 0xFE
        with self.assertRaisesRegex(GcLayoutError, "not erased"):
            build_gc_sector_layout(bytes(source), ((0x08, 0xF0),))
        with self.assertRaisesRegex(GcLayoutError, "duplicate"):
            build_gc_sector_layout(
                b"\xFF" * FLASH_SIZE, ((0x08, 0xFE), (0x08, 0xF0))
            )
        with self.assertRaisesRegex(GcLayoutError, "must be one of"):
            build_gc_sector_layout(b"\xFF" * FLASH_SIZE, ((0x08, 0x00),))


if __name__ == "__main__":
    unittest.main()
