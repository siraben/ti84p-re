#!/usr/bin/env python3
"""Regression tests for deterministic Flash-command replay."""

import unittest

from flash_hardware import FLASH_SIZE
from flash_replay import (
    FlashReplayError,
    active_certificate_half,
    apply_accepted_command,
    find_gc_phase_snapshots,
    gc_journal_phase,
    replay_accepted_commands,
)
from flash_trace import FlashCommand
from gc_journal import GC_BLOCK_OFFSET, MASTER_PHASE_OFFSET


def command(kind: str, clock: int, address: int, value: int) -> FlashCommand:
    return FlashCommand(kind, clock, clock, address, value, ())


class FlashReplayTests(unittest.TestCase):
    def test_program_uses_nor_bitwise_and(self):
        image = bytearray(b"\xFF" * FLASH_SIZE)
        image[0x20000] = 0x5A

        mutation = apply_accepted_command(
            image, command("byte_program", 1, 0x20000, 0xA5)
        )

        self.assertEqual(0x00, image[0x20000])
        self.assertEqual(1, mutation.changed_bytes)

    def test_sector_erase_uses_top_boot_geometry(self):
        image = bytearray(b"\xFF" * FLASH_SIZE)
        image[0xF8000] = 0
        image[0xF9FFF] = 0
        image[0xFA000] = 0

        mutation = apply_accepted_command(
            image, command("sector_erase", 1, 0xF9000, 0x30)
        )

        self.assertEqual((0xF8000, 0xFA000), (mutation.start, mutation.end))
        self.assertEqual(0xFF, image[0xF8000])
        self.assertEqual(0xFF, image[0xF9FFF])
        self.assertEqual(0x00, image[0xFA000])

    def test_array_reset_is_data_neutral(self):
        source = b"\xA5" * FLASH_SIZE
        result = replay_accepted_commands(
            source, (command("array_reset", 1, 0x20000, 0xF0),)
        )

        self.assertEqual(source, result.image)
        self.assertEqual(1, result.commands_applied)
        self.assertEqual((), result.mutations)

    def test_rejects_unmatched_write(self):
        with self.assertRaisesRegex(FlashReplayError, "unmatched Flash write"):
            replay_accepted_commands(
                b"\xFF" * FLASH_SIZE,
                (command("unmatched_write", 1, 0x20000, 0x12),),
            )

    def test_inclusive_clock_cutoff(self):
        source = b"\xFF" * FLASH_SIZE
        result = replay_accepted_commands(
            source,
            (
                command("byte_program", 10, 0x20000, 0xFE),
                command("byte_program", 20, 0x20001, 0xFC),
            ),
            stop_clock=10,
        )

        self.assertEqual(0xFE, result.image[0x20000])
        self.assertEqual(0xFF, result.image[0x20001])
        self.assertEqual(10, result.last_clock)

    def test_identifies_only_one_zero_marked_certificate_half(self):
        image = bytearray(b"\xFF" * FLASH_SIZE)
        image[0xF8000] = 0
        self.assertEqual(0xF8000, active_certificate_half(image))
        image[0xFA000] = 0
        self.assertIsNone(active_certificate_half(image))

    def test_idle_erased_gc_block_has_no_phase(self):
        image = bytearray(b"\xFF" * FLASH_SIZE)
        image[0xF8000] = 0
        self.assertIsNone(gc_journal_phase(image))

    def test_extracts_first_active_images_for_requested_phases(self):
        source = bytearray(b"\xFF" * FLASH_SIZE)
        source[0xF8000] = 0
        commands = (
            command("byte_program", 10, 0xFA000 + GC_BLOCK_OFFSET, 0xFB),
            command("byte_program", 20, 0xFA000 + MASTER_PHASE_OFFSET, 0xFF),
            command("sector_erase", 30, 0xF8000, 0x30),
            command("byte_program", 40, 0xFA000, 0x00),
            command("byte_program", 50, 0xFA000 + MASTER_PHASE_OFFSET, 0xFE),
            command("byte_program", 60, 0xFA000 + MASTER_PHASE_OFFSET, 0xE0),
        )

        snapshots = find_gc_phase_snapshots(source, commands, (0xFF, 0xFE, 0xE0))

        self.assertEqual((0xFF, 0xFE, 0xE0), tuple(s.phase for s in snapshots))
        self.assertEqual((40, 50, 60), tuple(s.trigger_clock for s in snapshots))
        self.assertEqual((0xFA000,) * 3, tuple(s.half_base for s in snapshots))
        self.assertEqual(
            (0xFF, 0xFE, 0xE0),
            tuple(s.replay.image[0xFA000 + MASTER_PHASE_OFFSET] for s in snapshots),
        )

    def test_reports_phase_missing_from_stream(self):
        source = bytearray(b"\xFF" * FLASH_SIZE)
        source[0xF8000] = 0
        with self.assertRaisesRegex(FlashReplayError, "0xFC"):
            find_gc_phase_snapshots(source, (), (0xFC,))


if __name__ == "__main__":
    unittest.main()
