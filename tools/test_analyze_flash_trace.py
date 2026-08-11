#!/usr/bin/env python3
"""Regression tests for structured Flash-trace invocation reports."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyze_flash_trace import invocation_report, structured_report
from flash_trace import FlashCommand, FlashProgramInvocation
from hardware_trace import ResolvedMemoryWrite, TraceHeader


class AnalyzeFlashTraceTests(unittest.TestCase):
    def test_structured_report_labels_write_attempts_and_command_shapes(self):
        header = TraceHeader(version=2, flags=0, range_start=0, range_end=0xFFFF)

        report = structured_report(Path("trace.tlmt"), header, [], 0, [], [])

        self.assertEqual(0, report["resolved_flash_write_attempts"])
        self.assertEqual({}, report["command_shape_counts"])
        self.assertNotIn("resolved_flash_writes", report)
        self.assertIn("does not record ASIC", report["write_semantics"])

    def test_report_labels_page_3e_skip_transition(self):
        first = FlashCommand("byte_program", 1, 10, 0xF7FFF, 0x40, ())
        second = FlashCommand("byte_program", 2, 20, 0xF4000, 0xE0, ())
        reset = FlashCommand("array_reset", 3, 30, 0xF4000, 0xF0, ())

        report = invocation_report(
            FlashProgramInvocation((first, second), reset)
        )

        self.assertEqual(["same-page-window-wrap"], report["transition_kinds"])
        self.assertEqual(
            [
                {
                    "from": 0xF7FFF,
                    "to": 0xF4000,
                    "kind": "same-page-window-wrap",
                }
            ],
            report["discontinuities"],
        )
        self.assertEqual(0xF4000, report["reset_address"])
        self.assertEqual("unknown-reset", report["worker_outcome"])

    def test_report_classifies_failure_reset_pc(self):
        reset_write = ResolvedMemoryWrite(
            instruction_index=3,
            clock=30,
            logical_pc=0x8175,
            pc_space="ram",
            pc_address=0x8175,
            logical_address=0x7FFF,
            value=0xF0,
            target_kind="flash",
            target_page=0x3D,
            page_offset=0x3FFF,
            flat_address=0xF7FFF,
            unresolved=False,
        )
        program = FlashCommand("byte_program", 1, 10, 0xF7FFF, 0xD0, ())
        reset = FlashCommand("array_reset", 3, 30, 0xF7FFF, 0xF0, (reset_write,))

        report = invocation_report(FlashProgramInvocation((program,), reset))

        self.assertEqual(
            {"space": "ram", "address": 0x8175},
            report["reset_pc"],
        )
        self.assertEqual("failure", report["worker_outcome"])


if __name__ == "__main__":
    unittest.main()
