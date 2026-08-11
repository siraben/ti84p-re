#!/usr/bin/env python3
"""Regression tests for the general resolved memory-write analyzer."""

import argparse
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_memory_writes import (
    matching_writes,
    memory_write_report,
    parse_logical_address,
)
from hardware_trace import ResolvedMemoryWrite


def memory_write(**changes) -> ResolvedMemoryWrite:
    values = {
        "instruction_index": 1,
        "clock": 100,
        "logical_pc": 0x816B,
        "pc_space": "ram",
        "pc_address": 0x816B,
        "logical_address": 0x8000,
        "value": 0xF0,
        "target_kind": "ram",
        "target_page": 0,
        "page_offset": 0,
        "flat_address": None,
        "unresolved": False,
    }
    values.update(changes)
    return ResolvedMemoryWrite(**values)


class AnalyzeMemoryWritesTests(unittest.TestCase):
    def test_filters_logical_target_pc_and_clock_together(self):
        events = (
            memory_write(instruction_index=1),
            memory_write(instruction_index=2, logical_address=0x8001),
            memory_write(instruction_index=3, target_kind="flash"),
            memory_write(instruction_index=4, pc_address=0x8149),
            memory_write(instruction_index=5, clock=200),
        )

        selected = list(
            matching_writes(
                events,
                logical_addresses={0x8000},
                pcs={("ram", 0x816B)},
                target_kinds={"ram"},
                clock=(50, 150),
            )
        )

        self.assertEqual([1], [event.instruction_index for event in selected])

    def test_report_preserves_resolved_write_fields(self):
        report = memory_write_report(memory_write())

        self.assertEqual(0x816B, report["pc_address"])
        self.assertEqual(0x8000, report["logical_address"])
        self.assertEqual(0xF0, report["value"])
        self.assertEqual("ram", report["target_kind"])
        self.assertFalse(report["unresolved"])

    def test_parses_16_bit_logical_address(self):
        self.assertEqual(0x8000, parse_logical_address("0x8000"))

    def test_rejects_out_of_range_logical_address(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_logical_address("0x10000")


if __name__ == "__main__":
    unittest.main()
