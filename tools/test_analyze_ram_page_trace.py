#!/usr/bin/env python3
"""Regression tests for physical RAM-page write resolution."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_ram_page_trace import WriteAttributor, map_ram_write
from tilem_trace_resolve import Banker, IDX_OPCODE, IDX_PC, IDX_WZ


def instruction(pc, opcode=0x00, wz=0x0000):
    fields = [0] * 23
    fields[IDX_PC] = pc
    fields[IDX_OPCODE] = opcode
    fields[IDX_WZ] = wz
    return tuple(fields)


class RamWriteMappingTests(unittest.TestCase):
    def test_paired_mode_uses_port6_pair_and_port7_high_window(self):
        banker = Banker(initial_port4=1, initial_port5=0,
                        initial_port6=0x83, initial_port7=0x84,
                        initial_port27=0, initial_port28=0)

        self.assertEqual((0x82, 0x0123, 1),
                         map_ram_write(banker, 0x4123))
        self.assertEqual((0x83, 0x0123, 2),
                         map_ram_write(banker, 0x8123))
        self.assertEqual((0x84, 0x0123, 3),
                         map_ram_write(banker, 0xC123))

    def test_independent_mode_uses_ports6_7_5(self):
        banker = Banker(initial_port4=0, initial_port5=5,
                        initial_port6=0x81, initial_port7=0x82,
                        initial_port27=0, initial_port28=0)

        self.assertEqual((0x81, 0x0123, 1),
                         map_ram_write(banker, 0x4123))
        self.assertEqual((0x82, 0x0123, 2),
                         map_ram_write(banker, 0x8123))
        self.assertEqual((0x85, 0x0123, 3),
                         map_ram_write(banker, 0xC123))

    def test_unknown_or_flash_mapping_is_not_a_ram_write(self):
        self.assertIsNone(map_ram_write(Banker(), 0xC123))
        self.assertIsNone(map_ram_write(Banker.ti84p_reset(), 0xC123))
        self.assertIsNone(map_ram_write(Banker.ti84p_reset(), 0x0123))

    def test_forced_ram_ranges_override_flash_windows(self):
        banker = Banker(initial_port4=1, initial_port5=0,
                        initial_port6=2, initial_port7=3,
                        initial_port27=1, initial_port28=1)

        self.assertEqual((0x81, 0, 2), map_ram_write(banker, 0x8000))
        self.assertIsNone(map_ram_write(banker, 0x8040))
        self.assertIsNone(map_ram_write(banker, 0xFFBF))
        self.assertEqual((0x80, 0x3FC0, 3),
                         map_ram_write(banker, 0xFFC0))


class WriteAttributorTests(unittest.TestCase):
    def make_attributor(self):
        banker = Banker(initial_port4=0, initial_port5=0,
                        initial_port6=2, initial_port7=0x83,
                        initial_port27=0, initial_port28=0)
        return WriteAttributor(banker)

    def test_write_is_attributed_to_following_instruction_record(self):
        attributor = self.make_attributor()
        attributor.feed(0x01, instruction(0x1000))
        attributor.feed(0x02, (0x8123, 0xAA))

        events = attributor.feed(0x01, instruction(0x2345))

        self.assertEqual(1, len(events))
        instr_idx, logical, value, mapped, pc, resolved, unresolved = events[0]
        self.assertEqual(1, instr_idx)
        self.assertEqual((0x8123, 0xAA), (logical, value))
        self.assertEqual((0x83, 0x0123, 2), mapped)
        self.assertEqual(0x2345, pc)
        self.assertEqual(("ram", 0x2345), resolved)
        self.assertFalse(unresolved)

    def test_mapping_out_applies_before_next_instruction_writes(self):
        attributor = self.make_attributor()
        attributor.feed(0x01, instruction(0x1000, opcode=0xD3, wz=0x8207))
        attributor.feed(0x02, (0x8010, 0x55))

        events = attributor.feed(0x01, instruction(0x1001))

        self.assertEqual((0x82, 0x0010, 2), events[0][3])

    def test_trailing_write_remains_pending_without_instruction(self):
        attributor = self.make_attributor()

        attributor.feed(0x02, (0x8123, 0xAA))

        self.assertEqual(1, len(attributor.pending))


if __name__ == "__main__":
    unittest.main()
