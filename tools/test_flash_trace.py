#!/usr/bin/env python3
"""Regression tests for AMD Flash command decoding."""

import unittest

from flash_trace import (
    FlashCommand,
    decode_amd_flash_commands,
    flash_sector,
    group_byte_program_runs,
)
from hardware_trace import ResolvedMemoryWrite


def flash_write(address: int, value: int, index: int) -> ResolvedMemoryWrite:
    page, offset = divmod(address, 0x4000)
    return ResolvedMemoryWrite(
        instruction_index=index,
        clock=index * 10,
        logical_pc=0x8100,
        pc_space="ram",
        pc_address=0x8100,
        logical_address=0x4000 + offset,
        value=value,
        target_kind="flash",
        target_page=page,
        page_offset=offset,
        flat_address=address,
        unresolved=False,
    )


class FlashTraceTests(unittest.TestCase):
    def test_decodes_byte_program_sequence(self):
        writes = [
            flash_write(0xAAAA, 0xAA, 0),
            flash_write(0x5555, 0x55, 1),
            flash_write(0xAAAA, 0xA0, 2),
            flash_write(0x20000, 0xFC, 3),
        ]

        commands = list(decode_amd_flash_commands(writes))

        self.assertEqual(1, len(commands))
        self.assertEqual("byte_program", commands[0].kind)
        self.assertEqual((0x20000, 0xFC),
                         (commands[0].target_address, commands[0].value))

    def test_decodes_sector_erase_sequence(self):
        writes = [
            flash_write(0xAAAA, 0xAA, 0),
            flash_write(0x5555, 0x55, 1),
            flash_write(0xAAAA, 0x80, 2),
            flash_write(0xAAAA, 0xAA, 3),
            flash_write(0x5555, 0x55, 4),
            flash_write(0x30000, 0x30, 5),
        ]

        command = list(decode_amd_flash_commands(writes))[0]

        self.assertEqual("sector_erase", command.kind)
        self.assertEqual(0x30000, command.target_address)

    def test_reports_reset_and_unmatched_writes(self):
        commands = list(
            decode_amd_flash_commands(
                [flash_write(0x20000, 0xF0, 0), flash_write(0x20001, 0x12, 1)]
            )
        )

        self.assertEqual(["array_reset", "unmatched_write"],
                         [command.kind for command in commands])

    def test_top_boot_sector_geometry(self):
        self.assertEqual((0xE0000, 0x10000),
                         tuple(flash_sector(0xE1234).__dict__.values()))
        self.assertEqual((0xF0000, 0x8000),
                         tuple(flash_sector(0xF1234).__dict__.values()))
        self.assertEqual((0xF8000, 0x2000),
                         tuple(flash_sector(0xF9000).__dict__.values()))
        self.assertEqual((0xFA000, 0x2000),
                         tuple(flash_sector(0xFA000).__dict__.values()))
        self.assertEqual((0xFC000, 0x4000),
                         tuple(flash_sector(0xFFFFF).__dict__.values()))

    def test_groups_adjacent_program_commands_but_not_clock_gaps(self):
        def command(address, index):
            write = flash_write(address, index, index)
            return FlashCommand(
                "byte_program", index, write.clock, address, index, (write,)
            )

        commands = [
            command(0x20000, 1),
            FlashCommand("array_reset", 2, 15, 0x20000, 0xF0, ()),
            command(0x20001, 2),
            command(0x20002, 20_000),
            FlashCommand("sector_erase", 20_001, 200_010, 0x30000, 0x30, ()),
            command(0x30000, 20_002),
        ]

        runs = list(group_byte_program_runs(commands, max_clock_gap=100_000))

        self.assertEqual(
            [(0x20000, 0x20001), (0x20002, 0x20002), (0x30000, 0x30000)],
            [(run.start_address, run.end_address) for run in runs],
        )


if __name__ == "__main__":
    unittest.main()
