#!/usr/bin/env python3
"""Regression tests for low-allocation hardware-trace helpers."""

import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hardware_trace import count_resolved_trace_points
from tilem_trace_resolve import HEADER_FMT, IDX_WZ, INSTR_FMT


def instruction_record(pc: int, opcode: int, clock: int, *, wz: int = 0) -> bytes:
    fields = [pc, opcode, clock] + [0] * 15 + [0] * 5
    fields[IDX_WZ] = wz
    return b"\x01" + struct.pack(INSTR_FMT, *fields)


class HardwareTraceTests(unittest.TestCase):
    def test_point_counter_rejects_unsupported_trace_version(self):
        with tempfile.NamedTemporaryFile() as trace:
            trace.write(struct.pack(HEADER_FMT, b"TLMT", 1, 7, 0, 0xFFFF, 0))
            trace.flush()
            with self.assertRaisesRegex(ValueError, "unsupported TLMT version 1"):
                count_resolved_trace_points(Path(trace.name), set())

    def test_point_counter_replays_mapping_without_retaining_instructions(self):
        with tempfile.NamedTemporaryFile() as trace:
            trace.write(struct.pack(HEADER_FMT, b"TLMT", 2, 7, 0, 0xFFFF, 0))
            trace.write(instruction_record(0x8002, 0x00, 1))
            trace.write(
                instruction_record(0x8100, 0xD3, 2, wz=(0x02 << 8) | 0x06)
            )
            trace.write(instruction_record(0x4000, 0x00, 3))
            trace.flush()

            report = count_resolved_trace_points(
                Path(trace.name),
                {("page_3F", 0x4002), ("page_02", 0x4000)},
                initial_mapping="ti84p-reset",
            )

        self.assertEqual(3, report.processed_instructions)
        self.assertEqual(
            {("page_3F", 0x4002): 1, ("page_02", 0x4000): 1},
            report.counts,
        )

    def test_point_counter_does_not_attribute_nearby_pcs_to_symbol_entry(self):
        with tempfile.NamedTemporaryFile() as trace:
            trace.write(struct.pack(HEADER_FMT, b"TLMT", 2, 7, 0, 0xFFFF, 0))
            trace.write(instruction_record(0x51F1, 0x00, 1))
            trace.write(instruction_record(0x51F3, 0x00, 2))
            trace.flush()

            report = count_resolved_trace_points(
                Path(trace.name),
                {("page_39", 0x5167), ("page_39", 0x51F1)},
                initial_port4=0,
                initial_port5=0,
                initial_port6=0x39,
                initial_port7=0x3F,
                initial_port27=0,
                initial_port28=0,
            )

        self.assertEqual({("page_39", 0x51F1): 1}, report.counts)


if __name__ == "__main__":
    unittest.main()
