#!/usr/bin/env python3
"""Regression tests for emulator-specific execution-protection models."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from execution_protection import (
    TI84P_BOOT_PROTECTION,
    WabbitemuProtectionPortModel,
    tilem_flash_execution_allowed,
    tilem_ram_execution_allowed,
    tilem_ram_mask,
    tilem_ram_page_coverage,
    wabbitemu_flash_execution_allowed,
    wabbitemu_ram_execution_allowed,
    wabbitemu_ram_page_coverage,
)


class ExecutionProtectionTests(unittest.TestCase):
    def test_wabbitemu_boundary_ports_share_the_flash_lock_gate(self):
        model = WabbitemuProtectionPortModel()

        self.assertFalse(model.write_port(0x22, 0xAA))
        self.assertEqual(0x10, model.read_port(0x22))

        model.flash_locked = False
        self.assertTrue(model.write_port(0x22, 0xAA))
        self.assertEqual(0xAA, model.read_port(0x22))

    def test_wabbitemu_port24_clears_seeded_high_bits(self):
        model = WabbitemuProtectionPortModel(
            flash_locked=False,
            flash_lower=0x01CC,
            flash_upper=0x02DD,
        )

        self.assertTrue(model.write_port(0x24, 0xFF))

        self.assertEqual(0xFF, model.read_port(0x24))
        self.assertEqual(0x00CC, model.flash_lower)
        self.assertEqual(0x00DD, model.flash_upper)

    def test_wabbitemu_ram_port_fields_wrap_at_16_bits(self):
        model = WabbitemuProtectionPortModel(flash_locked=False)

        lower = []
        upper = []
        for value in (0x3F, 0x40, 0x41, 0xFF):
            self.assertTrue(model.write_port(0x25, value))
            lower.append((model.read_port(0x25), model.ram_lower))
            self.assertTrue(model.write_port(0x26, value))
            upper.append((model.read_port(0x26), model.ram_upper))

        self.assertEqual(
            [(0x3F, 0xFC00), (0x00, 0x0000), (0x01, 0x0400), (0x3F, 0xFC00)],
            lower,
        )
        self.assertEqual(
            [(0x3F, 0xFFFF), (0x00, 0x03FF), (0x01, 0x07FF), (0x3F, 0xFFFF)],
            upper,
        )

    def test_boot_register_values(self):
        self.assertEqual(0, TI84P_BOOT_PROTECTION.ram_mode)
        self.assertEqual(0x08, TI84P_BOOT_PROTECTION.flash_lower)
        self.assertEqual(0x29, TI84P_BOOT_PROTECTION.flash_upper)
        self.assertEqual(0x10, TI84P_BOOT_PROTECTION.ram_lower_chunk)
        self.assertEqual(0x20, TI84P_BOOT_PROTECTION.ram_upper_chunk)

    def test_tilem_flash_interval_is_inclusive(self):
        allowed = lambda page: tilem_flash_execution_allowed(page, 0x08, 0x29)
        self.assertTrue(allowed(0x07))
        self.assertFalse(allowed(0x08))
        self.assertFalse(allowed(0x29))
        self.assertTrue(allowed(0x2A))

    def test_reversed_flash_bounds_allow_every_page(self):
        self.assertTrue(
            all(tilem_flash_execution_allowed(page, 0x29, 0x08) for page in range(0x40))
        )

    def test_wabbitemu_differs_at_flash_lower_edge(self):
        self.assertFalse(tilem_flash_execution_allowed(0x08, 0x08, 0x29))
        self.assertTrue(wabbitemu_flash_execution_allowed(0x08, 0x08, 0x29))
        self.assertFalse(wabbitemu_flash_execution_allowed(0x09, 0x08, 0x29))
        self.assertFalse(wabbitemu_flash_execution_allowed(0x29, 0x08, 0x29))

    def test_wabbitemu_always_allows_flash_page_zero(self):
        self.assertFalse(tilem_flash_execution_allowed(0, 0, 0))
        self.assertTrue(wabbitemu_flash_execution_allowed(0, 0, 0))

    def test_tilem_masks_for_all_modes(self):
        self.assertEqual(
            (0x7C00, 0xFC00, 0x1FC00, 0x3FC00),
            tuple(tilem_ram_mask(mode) for mode in range(4)),
        )

    def test_mode_zero_repeats_one_full_page_every_32_kib(self):
        coverage = tilem_ram_page_coverage(0, 0x10, 0x20)
        self.assertEqual(
            (0x81, 0x83, 0x85, 0x87),
            tuple(page.selector_page for page in coverage if page.fully_executable),
        )
        self.assertFalse(any(page.partly_executable for page in coverage))

    def test_mode_one_includes_upper_boundary_chunk(self):
        coverage = tilem_ram_page_coverage(1, 0x10, 0x20)
        self.assertEqual(
            (0x81, 0x85),
            tuple(page.selector_page for page in coverage if page.fully_executable),
        )
        self.assertEqual((0,), coverage[2].executable_chunks)
        self.assertEqual((0,), coverage[6].executable_chunks)
        self.assertTrue(tilem_ram_execution_allowed(0x8000, 1, 0x10, 0x20))
        self.assertTrue(tilem_ram_execution_allowed(0x83FF, 1, 0x10, 0x20))
        self.assertFalse(tilem_ram_execution_allowed(0x8400, 1, 0x10, 0x20))

    def test_modes_two_and_three_share_first_128_kib_coverage(self):
        expected = [(), tuple(range(16)), (0,), (), (), (), (), ()]
        for mode in (2, 3):
            with self.subTest(mode=mode):
                coverage = tilem_ram_page_coverage(mode, 0x10, 0x20)
                self.assertEqual(expected, [page.executable_chunks for page in coverage])

    def test_reversed_ram_bounds_deny_every_chunk(self):
        coverage = tilem_ram_page_coverage(0, 0x20, 0x10)
        self.assertFalse(any(page.executable_chunks for page in coverage))

    def test_wabbitemu_ram_shortcut_collapses_after_mode_zero(self):
        self.assertTrue(wabbitemu_ram_execution_allowed(3, 0, 0, 0x10, 0x20))
        for mode in (1, 2, 3):
            with self.subTest(mode=mode):
                self.assertFalse(
                    wabbitemu_ram_execution_allowed(3, 0, mode, 0x10, 0x20)
                )

    def test_wabbitemu_global_range_includes_complete_upper_chunk(self):
        self.assertTrue(wabbitemu_ram_execution_allowed(2, 0x000, 3, 0x10, 0x20))
        self.assertTrue(wabbitemu_ram_execution_allowed(2, 0x3FF, 3, 0x10, 0x20))
        self.assertFalse(wabbitemu_ram_execution_allowed(2, 0x400, 3, 0x10, 0x20))

    def test_wabbitemu_high_chunk_ports_wrap_to_16_bits(self):
        self.assertTrue(wabbitemu_ram_execution_allowed(0, 0, 3, 0x40, 0x40))
        self.assertTrue(wabbitemu_ram_execution_allowed(0, 0x3FF, 3, 0x40, 0x40))
        self.assertFalse(wabbitemu_ram_execution_allowed(4, 0, 3, 0x40, 0x40))

    def test_wabbitemu_default_page_coverage_matches_source_arithmetic(self):
        for mode in range(4):
            with self.subTest(mode=mode):
                coverage = wabbitemu_ram_page_coverage(mode, 0x10, 0x20)
                full_pages = tuple(
                    page.selector_page for page in coverage if page.fully_executable
                )
                expected = (0x81, 0x83, 0x85, 0x87) if mode == 0 else (0x81,)
                self.assertEqual(expected, full_pages)
                self.assertEqual((0,), coverage[2].executable_chunks)

    def test_invalid_values_are_rejected(self):
        with self.assertRaises(ValueError):
            tilem_ram_mask(4)
        with self.assertRaises(ValueError):
            tilem_flash_execution_allowed(0x100, 0, 0)
        with self.assertRaises(ValueError):
            wabbitemu_ram_execution_allowed(0, 0x4000, 0, 0, 0)


if __name__ == "__main__":
    unittest.main()
