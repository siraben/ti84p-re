#!/usr/bin/env python3
"""Regression tests for structural Flash-command candidate helpers."""

import unittest

from ti84re.flash.rom_commands import (
    command_values,
    direct_store_a_address,
    find_flash_unlock_write_candidates,
    immediate_a_value,
)
from ti84re.rom.image import RomLocation
from ti84re.rom.z80_disassembly import Z80Instruction


def instruction(address: int, data: bytes, text: str) -> Z80Instruction:
    return Z80Instruction(RomLocation(0x3F, address), data, text)


class FlashRomCommandTests(unittest.TestCase):
    def test_exact_instruction_decoders_use_bytes(self):
        load = instruction(0x4000, bytes((0x3E, 0xA0)), "ld a,0a0h")
        store = instruction(0x4002, bytes((0x32, 0xAA, 0x6A)), "ld (06aaah),a")

        self.assertEqual(0xA0, immediate_a_value(load))
        self.assertEqual(0x6AAA, direct_store_a_address(store))
        self.assertIsNone(immediate_a_value(store))

    def test_finds_only_unlock_address_stores_and_nearby_command_loads(self):
        instructions = (
            instruction(0x4000, bytes((0x3E, 0x98)), "ld a,098h"),
            instruction(0x4002, bytes((0x32, 0xAA, 0x6A)), "ld (06aaah),a"),
            instruction(0x4005, bytes((0x3E, 0x42)), "ld a,042h"),
            instruction(0x4007, bytes((0x32, 0x55, 0x55)), "ld (05555h),a"),
            instruction(0x400A, bytes((0x32, 0x00, 0x80)), "ld (08000h),a"),
        )

        candidates = tuple(find_flash_unlock_write_candidates(instructions))

        self.assertEqual(
            [0x6AAA, 0x5555],
            [item.target_address for item in candidates],
        )
        self.assertEqual(frozenset((0x98,)), command_values(candidates))
        self.assertEqual(-1, candidates[0].nearby_command_loads[0].distance)

    def test_context_validation(self):
        with self.assertRaises(ValueError):
            tuple(find_flash_unlock_write_candidates((), before=-1))


if __name__ == "__main__":
    unittest.main()
