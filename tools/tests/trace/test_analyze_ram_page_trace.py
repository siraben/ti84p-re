#!/usr/bin/env python3
"""Regression tests for physical RAM-page write resolution."""

import unittest
from pathlib import Path
import struct
import tempfile


from ti84re.trace.analyze_ram_page import map_ram_write
from ti84re.trace.hardware import MemoryWriteAttributor, iter_resolved_instructions
from ti84re.trace.resolve import (
    Banker,
    HEADER_FMT,
    INSTR_FMT,
    IDX_OPCODE,
    IDX_PC,
    IDX_WZ,
)


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


class RamInstructionMappingTests(unittest.TestCase):
    def test_resolved_instruction_reports_physical_ram_page(self):
        fields = instruction(0x8123)
        with tempfile.NamedTemporaryFile() as fp:
            fp.write(struct.pack(HEADER_FMT, b"TLMT", 2, 7, 0, 0xFFFF, 0))
            fp.write(b"\x01")
            fp.write(struct.pack(INSTR_FMT, *fields))
            fp.flush()

            events = list(
                iter_resolved_instructions(
                    Path(fp.name),
                    initial_port4=0,
                    initial_port5=0,
                    initial_port6=0x81,
                    initial_port7=0x85,
                    initial_port27=0,
                    initial_port28=0,
                )
            )

        self.assertEqual(1, len(events))
        self.assertEqual(
            ("ram", 0x8123, None, 5),
            (
                events[0].space,
                events[0].address,
                events[0].page,
                events[0].physical_page,
            ),
        )


class WriteAttributorTests(unittest.TestCase):
    def make_attributor(self):
        banker = Banker(initial_port4=0, initial_port5=0,
                        initial_port6=2, initial_port7=0x83,
                        initial_port27=0, initial_port28=0)
        return MemoryWriteAttributor(banker)

    def test_write_is_attributed_to_following_instruction_record(self):
        attributor = self.make_attributor()
        attributor.feed(0x01, instruction(0x1000))
        attributor.feed(0x02, (0x8123, 0xAA))

        events = attributor.feed(0x01, instruction(0x2345))

        self.assertEqual(1, len(events))
        event = events[0]
        self.assertEqual(1, event.instruction_index)
        self.assertEqual((0x8123, 0xAA), (event.logical_address, event.value))
        self.assertEqual(("ram", 0x83, 0x0123),
                         (event.target_kind, event.target_page,
                          event.page_offset))
        self.assertEqual(0x2345, event.logical_pc)
        self.assertEqual(("ram", 0x2345),
                         (event.pc_space, event.pc_address))
        self.assertFalse(event.unresolved)

    def test_mapping_out_applies_before_next_instruction_writes(self):
        attributor = self.make_attributor()
        attributor.feed(0x01, instruction(0x1000, opcode=0xD3, wz=0x8207))
        attributor.feed(0x02, (0x8010, 0x55))

        events = attributor.feed(0x01, instruction(0x1001))

        self.assertEqual(("ram", 0x82, 0x0010),
                         (events[0].target_kind, events[0].target_page,
                          events[0].page_offset))

    def test_trailing_write_remains_pending_without_instruction(self):
        attributor = self.make_attributor()

        attributor.feed(0x02, (0x8123, 0xAA))

        self.assertEqual(1, len(attributor.pending))


if __name__ == "__main__":
    unittest.main()
