#!/usr/bin/env python3
"""Regression tests for resolved trace-point parsing."""

import argparse
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_trace_points import (
    RegisterPredicate,
    TracePoint,
    matching_visits,
    parse_point,
    parse_predicate,
    register_summary,
)
from hardware_trace import ResolvedInstruction


def instruction(**changes) -> ResolvedInstruction:
    values = {
        "instruction_index": 0,
        "clock": 100,
        "logical_pc": 0x8100,
        "space": "ram",
        "address": 0x8100,
        "flat_address": None,
        "page": None,
        "physical_page": 1,
        "opcode": 0xE6,
        "af": 0,
        "bc": 1,
        "de": 0x4000,
        "hl": 0x8478,
        "ix": 0,
        "iy": 0,
        "sp": 0xFFF0,
        "wz": 0,
    }
    values.update(changes)
    return ResolvedInstruction(**values)


class TracePointTests(unittest.TestCase):
    def test_parses_overlay_point(self):
        self.assertEqual(
            TracePoint("page_3C", 0x7733),
            parse_point("page_3C:7733"),
        )

    def test_rejects_missing_space(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_point(":7733")

    def test_parses_case_insensitive_register_predicate(self):
        self.assertEqual(
            RegisterPredicate("HL", ">=", 0x8000),
            parse_predicate("hl >= 0x8000"),
        )

    def test_rejects_predicate_value_wider_than_register(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_predicate("HL<0x10000")

    def test_filters_by_point_opcode_register_and_clock(self):
        events = (
            instruction(instruction_index=0),
            instruction(instruction_index=1, hl=0x6000),
            instruction(instruction_index=2, opcode=0xF5),
            instruction(instruction_index=3, address=0x8101),
            instruction(instruction_index=4, clock=200),
        )

        visits = list(
            matching_visits(
                events,
                {("ram", 0x8100)},
                opcodes={0xE6},
                predicates=(RegisterPredicate("HL", ">=", 0x8000),),
                clock=(50, 150),
            )
        )

        self.assertEqual([0], [event.instruction_index for event in visits])

    def test_summarizes_register_values_in_numeric_order(self):
        summary = register_summary(
            (
                instruction(hl=0x8478),
                instruction(hl=0x8000),
                instruction(hl=0x8478),
            ),
            "HL",
        )

        self.assertEqual(
            [{"value": 0x8000, "count": 1}, {"value": 0x8478, "count": 2}],
            summary,
        )


if __name__ == "__main__":
    unittest.main()
