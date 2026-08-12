#!/usr/bin/env python3
"""Regression tests for TilEm TLMT LCD replay."""

import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tilem_trace_resolve import HEADER_FMT, IDX_AF, IDX_BC, IDX_CLOCK, IDX_OPCODE, IDX_WZ, INSTR_FMT
from trace_lcd import BUSY_CLOCKS, STRIDE, T6A04, reconstruct, replay_mutations


def instruction(opcode, clock, *, af=0, bc=0, wz=0, pc=0x8000):
    fields = [0] * 23
    fields[0] = pc
    fields[IDX_OPCODE] = opcode
    fields[IDX_CLOCK] = clock
    fields[IDX_AF] = af
    fields[IDX_BC] = bc
    fields[IDX_WZ] = wz
    return struct.pack(INSTR_FMT, *fields)


def trace_file(records):
    temp = tempfile.NamedTemporaryFile()
    temp.write(struct.pack(HEADER_FMT, b"TLMT", 2, 7, 0, 0xFFFF, 0))
    for record in records:
        temp.write(b"\x01" + record)
    temp.flush()
    return temp


class ControllerTests(unittest.TestCase):
    def test_ti84_plus_reset_state_and_hidden_columns(self):
        lcd = T6A04()
        self.assertEqual((1, 0, 7, STRIDE * 64),
                         (lcd.mode, lcd.active, lcd.inc, len(lcd.mem)))
        lcd.x = 12
        lcd.y = 0
        lcd.write(0xFF)
        self.assertEqual(0xFF, lcd.mem[12])
        self.assertFalse(any(any(row) for row in lcd.grid()))

    def test_six_bit_transfer_and_row_shift(self):
        lcd = T6A04()
        lcd.control(0)
        lcd.control(0x81)
        lcd.write(0b101010)
        lcd.control(0x41)
        self.assertEqual([1, 0, 1, 0, 1, 0], lcd.grid()[0][:6])

    def test_busy_write_is_rejected_without_extending_deadline(self):
        lcd = T6A04()
        self.assertTrue(lcd.control(0x20, 100))
        self.assertFalse(lcd.write(0xFF, 100 + BUSY_CLOCKS - 1))
        self.assertTrue(lcd.write(0x80, 100 + BUSY_CLOCKS))
        self.assertEqual(0x80, lcd.mem[0])

    def test_data_read_moves_pointer_and_obeys_busy_interval(self):
        lcd = T6A04()
        lcd.x = 3
        self.assertTrue(lcd.read(100))
        self.assertEqual(4, lcd.x)
        self.assertFalse(lcd.read(100 + BUSY_CLOCKS - 1))
        self.assertEqual(4, lcd.x)
        self.assertTrue(lcd.read(100 + BUSY_CLOCKS))
        self.assertEqual(5, lcd.x)


class TraceReplayTests(unittest.TestCase):
    def test_mutation_replay_preserves_set_and_clear_write_order(self):
        records = [
            instruction(0xD3, 100, af=0x2000, wz=0x2010),
            instruction(0xD3, 160, af=0x8000, wz=0x8011),
            instruction(0xD3, 220, af=0x2000, wz=0x2010),
            instruction(0xD3, 280, af=0x0000, wz=0x0011),
        ]
        with trace_file(records) as trace:
            replay = replay_mutations(trace.name, from_index=1)
        self.assertFalse(any(any(row) for row in replay.initial))
        self.assertEqual(
            [((0, 0, 1),), ((0, 0, 0),)],
            [event.changes for event in replay.events],
        )
        self.assertFalse(any(any(row) for row in replay.final))

    def test_mutation_replay_cutoff_starts_from_prior_lcd_state(self):
        records = [
            instruction(0xD3, 100, af=0x2000, wz=0x2010),
            instruction(0xD3, 160, af=0x8000, wz=0x8011),
            instruction(0xD3, 220, af=0x2100, wz=0x2110),
            instruction(0xD3, 280, af=0x4000, wz=0x4011),
        ]
        with trace_file(records) as trace:
            replay = replay_mutations(trace.name, from_index=2)
        self.assertEqual(1, replay.initial[0][0])
        self.assertEqual(((9, 0, 1),), replay.events[0].changes)
        self.assertEqual(1, replay.final[0][9])

    def test_immediate_register_and_mirrored_outputs(self):
        records = [
            # OUT (0x12),A: mirrored command, select column zero.
            instruction(0xD3, 100, af=0x2000, wz=0x2012),
            # OUT (C),A: mirrored data port. BC's low byte supplies the port.
            instruction(0xED79, 160, af=0x8000, bc=0x0013),
        ]
        with trace_file(records) as trace:
            grid = reconstruct(Path(trace.name))
        self.assertEqual(1, grid[0][0])
        self.assertEqual(0, grid[0][1])

    def test_cutoff_counts_instruction_records(self):
        records = [
            instruction(0xD3, 100, af=0x2000, wz=0x2010),
            instruction(0xD3, 160, af=0x8000, wz=0x8011),
        ]
        with trace_file(records) as trace:
            before_write = reconstruct(trace.name, at_index=1)
            after_write = reconstruct(trace.name)
        self.assertFalse(any(any(row) for row in before_write))
        self.assertEqual(1, after_write[0][0])

    def test_data_input_affects_following_write_address(self):
        records = [
            instruction(0xD3, 100, af=0x2000, wz=0x2010),
            instruction(0xDB, 160, af=0x0000, wz=0x0011),
            instruction(0xD3, 220, af=0x8000, wz=0x8011),
        ]
        with trace_file(records) as trace:
            grid = reconstruct(trace.name)
        self.assertEqual(0, grid[0][0])
        self.assertEqual(1, grid[0][8])

    def test_unknown_block_output_to_lcd_is_rejected(self):
        with trace_file([instruction(0xEDB3, 100, bc=0x0011)]) as trace:
            with self.assertRaisesRegex(ValueError, "cannot be replayed"):
                reconstruct(trace.name)

    def test_non_reset_origin_trace_is_rejected(self):
        with trace_file([instruction(0, 100, pc=0x4000)]) as trace:
            with self.assertRaisesRegex(ValueError, "first PC is 0x8000"):
                reconstruct(trace.name)

    def test_empty_trace_is_rejected(self):
        with trace_file([]) as trace:
            with self.assertRaisesRegex(ValueError, "at least one instruction"):
                reconstruct(trace.name)


if __name__ == "__main__":
    unittest.main()
