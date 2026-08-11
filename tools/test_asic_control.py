#!/usr/bin/env python3
"""Regression tests for TI-84 Plus ASIC-control decoders."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from asic_control import (
    decode_battery_configuration,
    decode_port02,
    decode_port15,
    decode_port21,
    iter_gpio_read_modify_writes,
)
from rom_image import RomLocation
from z80_disassembly import Z80Instruction


def instruction(address: int, text: str, data: bytes = b"\0") -> Z80Instruction:
    return Z80Instruction(RomLocation(0x33, address), data, text)


class AsicControlTests(unittest.TestCase):
    def test_decodes_observed_port02_values(self):
        locked = decode_port02(0xE3)
        waiting = decode_port02(0xE1)
        unlocked = decode_port02(0xE7)

        self.assertTrue(locked.battery_comparator_high)
        self.assertTrue(locked.lcd_ready)
        self.assertFalse(locked.flash_unlocked)
        self.assertFalse(waiting.lcd_ready)
        self.assertTrue(unlocked.flash_unlocked)

    def test_identity_table_and_unknown_value(self):
        identity = decode_port15(0x55)

        self.assertIsNotNone(identity)
        self.assertEqual(48, identity.ram_kib)
        self.assertIsNone(decode_port15(0x00))

    def test_port21_decodes_visible_fields_and_execution_pattern(self):
        mode0 = decode_port21(0xCC)
        mode2 = decode_port21(0x22)

        self.assertEqual(0x00, mode0.visible_value)
        self.assertEqual(0x7C00, mode0.tilem_ram_address_mask)
        self.assertEqual(4096, mode2.documented_flash_kib)
        self.assertEqual(128, mode2.documented_ram_kib)

    def test_decodes_tilem_battery_selector_without_reordering_it(self):
        self.assertEqual(43, decode_battery_configuration(0xC6).tilem_threshold_tenths_volt)
        self.assertEqual(36, decode_battery_configuration(0x86).tilem_threshold_tenths_volt)
        self.assertEqual(39, decode_battery_configuration(0x46).tilem_threshold_tenths_volt)
        self.assertEqual(33, decode_battery_configuration(0x06).tilem_threshold_tenths_volt)

    def test_finds_gpio_set_and_clear_sequences(self):
        instructions = (
            instruction(0x4000, "in a,(03ah)"),
            instruction(0x4002, "or 080h"),
            instruction(0x4004, "out (03ah),a"),
            instruction(0x4006, "in a,(039h)"),
            instruction(0x4008, "and 0efh"),
            instruction(0x400A, "out (039h),a"),
        )

        operations = tuple(iter_gpio_read_modify_writes(instructions))

        self.assertEqual(2, len(operations))
        self.assertEqual((0x3A, "set", 0x80), (
            operations[0].port,
            operations[0].operation,
            operations[0].mask,
        ))
        self.assertEqual((0x39, "clear", 0x10), (
            operations[1].port,
            operations[1].operation,
            operations[1].mask,
        ))

    def test_rejects_register_mismatch_and_non_gpio_ports(self):
        instructions = (
            instruction(0x4000, "in a,(03ah)"),
            instruction(0x4002, "or 080h"),
            instruction(0x4004, "out (039h),a"),
            instruction(0x4006, "in a,(002h)"),
            instruction(0x4008, "or 080h"),
            instruction(0x400A, "out (002h),a"),
        )

        self.assertEqual((), tuple(iter_gpio_read_modify_writes(instructions)))

    def test_register_values_must_be_bytes(self):
        with self.assertRaises(ValueError):
            decode_port02(0x100)


if __name__ == "__main__":
    unittest.main()
