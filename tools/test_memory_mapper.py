#!/usr/bin/env python3
"""Regression tests for the reusable TI-83 Plus-family mapper."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from memory_mapper import MAPPER_PROFILES, Ti83PlusMapper, mapper_profile


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
            profile="documented",
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
            profile="documented",
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

    def test_profile_lookup_rejects_unknown_name(self):
        self.assertEqual("mame0287", mapper_profile("MAME").revision)

        with self.assertRaisesRegex(ValueError, "unknown mapper profile"):
            mapper_profile("fictional")

    def test_profile_catalog_has_reference_and_three_emulators(self):
        self.assertEqual(
            {"documented", "tilem", "wabbitemu", "mame"},
            set(MAPPER_PROFILES),
        )

    def test_even_paired_selector_exposes_wabbitemu_expression_bug(self):
        expected = {
            "documented": (("flash", 2), ("flash", 3)),
            "tilem": (("flash", 2), ("flash", 3)),
            "wabbitemu": (("flash", 2), ("flash", 2)),
            "mame": (("flash", 2), ("flash", 3)),
        }

        for profile, windows in expected.items():
            with self.subTest(profile=profile):
                mapper = Ti83PlusMapper(
                    profile=profile,
                    initial_port4=1,
                    initial_port5=0,
                    initial_port6=2,
                    initial_port7=4,
                    initial_port0e=0,
                    initial_port0f=0,
                    initial_port27=0,
                    initial_port28=0,
                )
                self.assertEqual(windows[0], mapper.mapped_page(1))
                self.assertEqual(windows[1], mapper.mapped_page(2))

    def test_mame_masks_flash_writes_but_retains_ram_selectors(self):
        mapper = Ti83PlusMapper.ti84p_reset("mame")

        self.assertTrue(mapper.write_port(0x06, 0x7F))
        self.assertEqual(0x3F, mapper.bank_a)
        self.assertTrue(mapper.write_port(0x07, 0x87))
        self.assertEqual(0x87, mapper.bank_b)
        self.assertTrue(mapper.write_port(0x05, 0xFF))
        self.assertEqual(7, mapper.bank_c)

    def test_mame_ignores_unmapped_extended_and_overlay_ports(self):
        mapper = Ti83PlusMapper.ti84p_reset("mame")

        self.assertFalse(mapper.write_port(0x0E, 3))
        self.assertFalse(mapper.write_port(0x27, 0xFF))
        self.assertEqual([(0x0E, 3), (0x27, 0xFF)], mapper.ignored_writes)
        self.assertEqual([], mapper.forced_ranges())

    def test_mame_reset_starts_fixed_on_boot_page_and_clears_on_a_read(self):
        mapper = Ti83PlusMapper.ti84p_reset("mame")

        self.assertEqual(0, mapper.initial_pc)
        self.assertEqual(("flash", 0x3F), mapper.mapped_page(0))
        self.assertEqual(("flash", 0), mapper.mapped_page(1))
        self.assertEqual(("flash", 1), mapper.mapped_page(2))
        self.assertTrue(mapper.boot_latch)

        self.assertEqual(("flash", 0), mapper.read_address(0x4000))
        self.assertEqual(("flash", 0), mapper.mapped_page(0))
        self.assertFalse(mapper.boot_latch)

    def test_mame_independent_b_read_does_not_clear_boot_latch(self):
        mapper = Ti83PlusMapper.ti84p_reset("mame")
        mapper.write_port(0x04, 0)

        mapper.read_address(0x8000)

        self.assertTrue(mapper.boot_latch)
        self.assertEqual(("flash", 0x3F), mapper.mapped_page(0))

    def test_wabbitemu_reset_clears_fixed_boot_page_only_on_opcode_fetch(self):
        mapper = Ti83PlusMapper.ti84p_reset("wabbitemu")

        self.assertEqual(("flash", 0x3F), mapper.mapped_page(0))
        mapper.read_address(0x4000)
        self.assertTrue(mapper.boot_latch)
        mapper.read_address(0x4000, opcode_fetch=True)
        self.assertFalse(mapper.boot_latch)
        self.assertEqual(("flash", 0), mapper.mapped_page(0))

    def test_wabbitemu_paired_readback_uses_visible_windows(self):
        mapper = Ti83PlusMapper(
            profile="wabbitemu",
            initial_port4=1,
            initial_port5=5,
            initial_port6=2,
            initial_port7=0x83,
            initial_port0e=0,
            initial_port0f=0,
            initial_port27=0,
            initial_port28=0,
        )

        self.assertEqual(3, mapper.read_port(0x05))
        self.assertEqual(2, mapper.read_port(0x06))
        self.assertEqual(2, mapper.read_port(0x07))

    def test_mame_ram_page_seven_falls_outside_banked_memory_map(self):
        mapper = Ti83PlusMapper(
            profile="mame",
            initial_port4=0,
            initial_port5=7,
            initial_port6=0x87,
            initial_port7=0x86,
        )

        self.assertEqual((None, None), mapper.mapped_page(1))
        self.assertEqual(("ram", 0x86), mapper.mapped_page(2))
        self.assertEqual((None, None), mapper.mapped_page(3))
        self.assertFalse(mapper.mapping_complete())

        mapper.write_port(0x06, 0x88)
        self.assertEqual((None, None), mapper.mapped_page(1))

        mapper.write_port(0x04, 1)
        mapper.write_port(0x06, 0x86)
        self.assertEqual(("ram", 0x86), mapper.mapped_page(1))
        self.assertEqual((None, None), mapper.mapped_page(2))

        mapper.write_port(0x06, 0x87)
        self.assertEqual(("ram", 0x86), mapper.mapped_page(1))
        self.assertEqual((None, None), mapper.mapped_page(2))

    def test_wabbitemu_port27_cutoff_truncates_large_overlay(self):
        mapper = Ti83PlusMapper(
            profile="wabbitemu",
            initial_port4=0,
            initial_port5=3,
            initial_port6=2,
            initial_port7=4,
            initial_port0e=0,
            initial_port0f=0,
            initial_port27=0xFF,
            initial_port28=0,
        )

        self.assertEqual(("ram", 0x83), mapper.mapped_address(0xFB63))
        self.assertEqual(("ram", 0x80), mapper.mapped_address(0xFB64))
        self.assertEqual([(0xFB64, 0xFFFF, 0x80)], mapper.forced_ranges())

    def test_documented_profile_has_no_asserted_reset_preset(self):
        with self.assertRaisesRegex(ValueError, "no verified reset"):
            Ti83PlusMapper.ti84p_reset("documented")

    def test_reduced_ram_alias_maps_selectors_two_through_seven_together(self):
        mapper = Ti83PlusMapper(
            profile="wabbitemu",
            initial_port4=0,
            initial_port5=7,
            initial_port6=0x87,
            initial_port7=0x87,
            initial_port0e=0,
            initial_port0f=0,
            initial_port27=0,
            initial_port28=0,
            ram_alias_from=2,
        )

        self.assertEqual(("ram", 0x82), mapper.mapped_page(1))
        self.assertEqual(("ram", 0x82), mapper.mapped_page(2))
        self.assertEqual(("ram", 0x82), mapper.mapped_page(3))
        self.assertEqual(0x87, mapper.read_port(0x06))
        self.assertEqual(0x87, mapper.read_port(0x07))
        self.assertEqual(7, mapper.read_port(0x05))

        mapper.write_port(0x04, 1)
        mapper.write_port(0x06, 0x87)
        self.assertEqual(("ram", 0x82), mapper.mapped_page(1))
        self.assertEqual(("ram", 0x82), mapper.mapped_page(2))

    def test_ram_alias_page_must_exist(self):
        with self.assertRaisesRegex(ValueError, "alias page must exist"):
            Ti83PlusMapper(ram_pages=8, ram_alias_from=8)


if __name__ == "__main__":
    unittest.main()
