#!/usr/bin/env python3
"""Regression tests for the retail boot hardware analysis."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from boot_hardware import (
    BOOT_PORT_WRITES,
    first_ram_test_mismatch,
    observe_reset_delay_trace,
    protected_flash_gate_writes,
    ram_test_pattern,
    reset_delay,
    validate_boot_port_writes,
)
from hardware_trace import ResolvedInstruction
from rom_image import RomImage

TOOLS = Path(__file__).resolve().parent


class BootHardwareTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = RomImage.from_path(TOOLS / "rom.bin")

    def test_reset_delay_counts_and_standard_timing(self):
        report = reset_delay()

        self.assertEqual(518, report.outer_iterations)
        self.assertEqual(132_608, report.djnz_executions)
        self.assertEqual(134_683, report.total_instruction_count)
        self.assertEqual(1_747_727, report.standard_loop_tstates)
        self.assertEqual(1_747_752, report.standard_total_tstates)
        self.assertEqual(1_746_716, report.tilem_total_tstates)
        self.assertEqual(1_036, report.tilem_difference_tstates)

    def test_observes_reset_delay_trace_boundaries(self):
        def event(index, address, clock):
            return ResolvedInstruction(
                index,
                clock,
                address,
                "page_3F",
                address,
                None,
                0x3F,
                None,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            )

        observation = observe_reset_delay_trace(
            (
                event(6, 0x400C, 64),
                event(7, 0x412C, 72),
                event(8, 0x412E, 79),
                event(9, 0x413D, 100),
                event(10, 0x413F, 110),
            )
        )

        self.assertEqual(3, observation.total_instruction_count)
        self.assertEqual(36, observation.elapsed_tstates)

    def test_boot_port_manifest_matches_rom_opcodes_and_values(self):
        self.assertEqual((), validate_boot_port_writes(self.rom))
        self.assertEqual(35, len(BOOT_PORT_WRITES))

    def test_classifies_every_protected_flash_gate_write(self):
        writes = protected_flash_gate_writes(self.rom)

        self.assertEqual(26, len(writes))
        self.assertEqual(10, sum(item.action == "enable" for item in writes))
        self.assertEqual(16, sum(item.action == "disable" for item in writes))
        self.assertTrue(all(item.safety_checks for item in writes if item.value))
        self.assertTrue(all(not item.safety_checks for item in writes if not item.value))

    def test_ram_pattern_repeats_zero_through_fa(self):
        pattern = ram_test_pattern(0xFB * 2 + 2)

        self.assertEqual(bytes(range(0xFB)), pattern[:0xFB])
        self.assertEqual(bytes(range(0xFB)), pattern[0xFB : 0x1F6])
        self.assertEqual(b"\x00\x01", pattern[-2:])
        self.assertIsNone(first_ram_test_mismatch(pattern))

        damaged = bytearray(pattern)
        damaged[0xFC] ^= 0x80
        self.assertEqual(0xFC, first_ram_test_mismatch(damaged))

    def test_ram_pattern_rejects_impossible_length(self):
        with self.assertRaises(ValueError):
            ram_test_pattern(0x10001)


if __name__ == "__main__":
    unittest.main()
