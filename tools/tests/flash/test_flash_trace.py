#!/usr/bin/env python3
"""Regression tests for AMD Flash command decoding."""

from dataclasses import replace
import unittest

from ti84re.flash.trace import (
    FLASH_WRITE_SEMANTICS,
    FlashCommand,
    decode_amd_flash_commands,
    group_byte_program_invocations,
    group_byte_program_runs,
    program_transition_kind,
)
from ti84re.flash.hardware import flash_sector
from ti84re.trace.hardware import ResolvedMemoryWrite


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
    def test_write_semantics_do_not_claim_asic_acceptance(self):
        self.assertIn("CPU write attempts", FLASH_WRITE_SEMANTICS)
        self.assertIn(
            "does not record ASIC or device acceptance",
            FLASH_WRITE_SEMANTICS,
        )

    def test_classifies_normal_crossing_and_same_page_window_wrap(self):
        self.assertEqual("contiguous", program_transition_kind(0x20000, 0x20001))
        self.assertEqual("next-page", program_transition_kind(0x23FFF, 0x24000))
        self.assertEqual(
            "same-page-window-wrap",
            program_transition_kind(0xF7FFF, 0xF4000),
        )
        self.assertEqual("discontinuity", program_transition_kind(0x20010, 0x20020))
        with self.assertRaisesRegex(ValueError, "outside"):
            program_transition_kind(0xFFFFF, 0x100000)

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

    def test_groups_worker_invocations_at_array_reset(self):
        def command(kind, address, index, value=0):
            write = flash_write(address, value, index)
            return FlashCommand(kind, index, write.clock, address, value, (write,))

        commands = [
            command("byte_program", 0x23FFF, 1),
            command("byte_program", 0x24000, 2),
            command("array_reset", 0x24000, 3, 0xF0),
            command("byte_program", 0x27FFF, 4),
            command("byte_program", 0x24000, 5),
            command("array_reset", 0x24000, 6, 0xF0),
        ]

        invocations = list(group_byte_program_invocations(commands))

        self.assertEqual(2, len(invocations))
        self.assertEqual((0x08, 0x09), invocations[0].pages)
        self.assertEqual(1, invocations[0].page_crossings)
        self.assertTrue(invocations[0].contiguous)
        self.assertTrue(invocations[0].reset_matches_final_target)
        self.assertEqual("unknown-reset", invocations[0].worker_outcome)
        self.assertEqual((0x09,), invocations[1].pages)
        self.assertFalse(invocations[1].contiguous)

    def test_reports_page_3e_skip_as_same_page_window_wrap(self):
        commands = [
            FlashCommand(
                "byte_program",
                1,
                10,
                0xF7FFF,
                0x40,
                (flash_write(0xF7FFF, 0x40, 1),),
            ),
            FlashCommand(
                "byte_program",
                2,
                20,
                0xF4000,
                0xE0,
                (flash_write(0xF4000, 0xE0, 2),),
            ),
            FlashCommand(
                "array_reset",
                3,
                30,
                0xF4000,
                0xF0,
                (flash_write(0xF4000, 0xF0, 3),),
            ),
        ]

        invocation = list(group_byte_program_invocations(commands))[0]

        self.assertEqual(("same-page-window-wrap",), invocation.transition_kinds)
        self.assertEqual((0x3D,), invocation.pages)
        self.assertEqual(0, invocation.page_crossings)
        self.assertFalse(invocation.contiguous)

    def test_keeps_unterminated_program_invocation(self):
        write = flash_write(0x20000, 0x12, 1)
        program = FlashCommand("byte_program", 1, 10, 0x20000, 0x12, (write,))
        erase = FlashCommand("sector_erase", 2, 20, 0x30000, 0x30, ())

        invocation = list(group_byte_program_invocations((program, erase)))[0]

        self.assertIsNone(invocation.reset)
        self.assertFalse(invocation.reset_matches_final_target)
        self.assertEqual("unterminated", invocation.worker_outcome)

    def test_classifies_copied_worker_reset_paths(self):
        program_write = flash_write(0xF7FFF, 0xD0, 1)
        program = FlashCommand(
            "byte_program", 1, 10, 0xF7FFF, 0xD0, (program_write,)
        )

        outcomes = []
        for pc_address in (0x816B, 0x8175, 0x8172, 0x817B):
            reset_write = replace(
                flash_write(0xF7FFF, 0xF0, 2),
                pc_address=pc_address,
            )
            reset = FlashCommand(
                "array_reset", 2, 20, 0xF7FFF, 0xF0, (reset_write,)
            )
            outcomes.append(
                list(group_byte_program_invocations((program, reset)))[0].worker_outcome
            )

        self.assertEqual(
            [
                "success",
                "failure",
                "certificate-success",
                "certificate-failure",
            ],
            outcomes,
        )


if __name__ == "__main__":
    unittest.main()
