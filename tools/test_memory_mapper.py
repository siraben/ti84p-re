#!/usr/bin/env python3
"""Regression tests for the reusable TI-83 Plus-family mapper."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from memory_mapper import Ti83PlusMapper


class MemoryMapperTests(unittest.TestCase):
    def test_ti84p_reset_uses_paired_boot_pages(self):
        mapper = Ti83PlusMapper.ti84p_reset()

        self.assertEqual(("flash", 0x3E), mapper.mapped_page(1))
        self.assertEqual(("flash", 0x3F), mapper.mapped_page(2))
        self.assertEqual(("flash", 0x3F), mapper.mapped_page(3))
        self.assertTrue(mapper.mapping_complete())

    def test_independent_mode_uses_three_independent_selectors(self):
        mapper = Ti83PlusMapper(
            initial_port4=0,
            initial_port5=3,
            initial_port6=2,
            initial_port7=4,
            initial_port27=0,
            initial_port28=0,
        )

        self.assertEqual(("flash", 2), mapper.mapped_page(1))
        self.assertEqual(("flash", 4), mapper.mapped_page(2))
        self.assertEqual(("ram", 0x83), mapper.mapped_page(3))

    def test_extended_flash_bits_select_large_device_page(self):
        mapper = Ti83PlusMapper(
            flash_pages=512,
            initial_port4=0,
            initial_port5=0,
            initial_port6=0,
            initial_port7=0x7F,
            initial_port0e=3,
            initial_port0f=2,
            initial_port27=0,
            initial_port28=0,
        )

        self.assertEqual(("flash", 0x180), mapper.mapped_page(1))
        self.assertEqual(("flash", 0x17F), mapper.mapped_page(2))

    def test_extended_flash_bits_are_irrelevant_on_ti84p(self):
        mapper = Ti83PlusMapper(
            flash_pages=64,
            initial_port4=0,
            initial_port5=0,
            initial_port6=0x7F,
            initial_port7=0,
            initial_port0e=None,
            initial_port0f=None,
            initial_port27=0,
            initial_port28=0,
        )

        self.assertEqual(("flash", 0x3F), mapper.mapped_page(1))

    def test_ram_selector_ignores_extended_flash_bits(self):
        mapper = Ti83PlusMapper(
            flash_pages=512,
            initial_port4=0,
            initial_port5=0,
            initial_port6=0x83,
            initial_port7=0,
            initial_port0e=None,
            initial_port0f=None,
            initial_port27=0,
            initial_port28=0,
        )

        self.assertEqual(("ram", 0x83), mapper.mapped_page(1))

    def test_high_page_register_writes_keep_two_bits(self):
        mapper = Ti83PlusMapper.ti84p_reset()

        self.assertTrue(mapper.write_port(0x0E, 0x1F))

        self.assertEqual(3, mapper.port0e)
        self.assertEqual(1, mapper.switches)

    def test_forced_ram_range_boundaries(self):
        mapper = Ti83PlusMapper(
            initial_port4=1,
            initial_port5=0,
            initial_port6=2,
            initial_port7=3,
            initial_port27=1,
            initial_port28=1,
        )

        self.assertEqual(("ram", 0x81), mapper.mapped_address(0x8000))
        self.assertEqual(("ram", 0x81), mapper.mapped_address(0x803F))
        self.assertEqual(("flash", 3), mapper.mapped_address(0x8040))
        self.assertEqual(("flash", 3), mapper.mapped_address(0xFFBF))
        self.assertEqual(("ram", 0x80), mapper.mapped_address(0xFFC0))

    def test_forced_overlays_can_be_disabled_in_paired_mode(self):
        mapper = Ti83PlusMapper(
            initial_port4=1,
            initial_port5=0,
            initial_port6=2,
            initial_port7=3,
            initial_port27=1,
            initial_port28=1,
            overlays_in_paired_mode=False,
        )

        self.assertEqual(("flash", 3), mapper.mapped_address(0x8000))
        self.assertEqual(("flash", 3), mapper.mapped_address(0xFFC0))
        self.assertEqual([], mapper.forced_ranges())


if __name__ == "__main__":
    unittest.main()
