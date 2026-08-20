"""Regression tests for the natural function-mode graph trace reducer."""

from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest

from analyze_graph_regraph import analyze_trace, summarize_sequence
from tilem_trace_resolve import HEADER_FMT, INSTR_FMT, MAGIC


REPORT = Path(__file__).resolve().with_name("graph-regraph.json")


def instruction(pc: int, opcode: int, clock: int, *, wz: int = 0) -> bytes:
    fields = [0] * 20
    fields[9] = wz
    return b"\x01" + struct.pack(INSTR_FMT, pc, opcode, clock, *fields)


def memory_write(address: int, value: int) -> bytes:
    return b"\x02" + struct.pack("<IB", address, value)


class GraphRegraphTests(unittest.TestCase):
    def test_sequence_summary_recognizes_unit_stride(self) -> None:
        self.assertEqual(
            summarize_sequence([0, 1, 2, 3]),
            {"count": 4, "first": 0, "last": 3, "distinct": 4, "stride": 1},
        )

    def test_minimal_trace_reduces_one_regraph_interval(self) -> None:
        initial = bytes(0x10000)
        header = struct.pack(HEADER_FMT, MAGIC, 2, 7, 0, 0xFFFF, len(initial))
        body = b"".join((
            instruction(0x0000, 0xD3, 1, wz=0x0406),  # map page 04 at 4000-7fff
            instruction(0x6764, 0xFB, 10),
            instruction(0x68D6, 0xCD, 20),
            instruction(0x69CF, 0x3A, 30),
            memory_write(0x8E67, 1),
            memory_write(0x9151, 1),
            instruction(0x69DB, 0x32, 40),
            memory_write(0x9340, 0x80),
            instruction(0x4290, 0x77, 50),
            instruction(0x6985, 0xC9, 60),
            memory_write(0x9151, 2),
            memory_write(0x9340, 0),
            instruction(0x0001, 0x00, 70),
        ))
        with tempfile.TemporaryDirectory() as directory:
            trace = Path(directory) / "minimal.trace"
            trace.write_bytes(header + initial + body)
            row = analyze_trace(trace)
        self.assertEqual(row["regraph_interval"]["post_entry_instruction_span"], 5)
        self.assertEqual(row["sample_columns_before_advance"]["first"], 0)
        self.assertEqual(row["plot_screen"]["writes"], 1)
        self.assertEqual(row["plot_screen"]["set_pixels"], 1)
        self.assertEqual(row["xres_int_at_return"], 1)

    def test_checked_report_records_natural_function_graphs(self) -> None:
        report = json.loads(REPORT.read_text())
        squared = report["scenarios"]["x_squared"]
        reciprocal = report["scenarios"]["reciprocal"]
        self.assertEqual(squared["sample_columns_before_advance"]["count"], 95)
        self.assertEqual(squared["sample_columns_before_advance"]["stride"], 1)
        self.assertEqual(squared["post_function_mode_visits"]["integer_line"], 30)
        self.assertEqual(squared["plot_screen"]["set_pixels"], 261)
        self.assertIn("documented_parseinp", squared["not_observed"])
        self.assertIn("token_prescan", squared["not_observed"])
        x_entry = squared["coordinate_witnesses"]["x"]["entry"]
        self.assertEqual(x_entry["column"], 33)
        self.assertEqual(x_entry["input_at_de"]["address"], "ram:84A4")
        self.assertEqual(x_entry["input_at_de"]["bytes"], "808029787234040000")
        self.assertEqual(
            squared["coordinate_witnesses"]["y"]["entry"]["input_at_de"],
            {"address": "ram:84AF", "bytes": "008088727931180000"},
        )
        self.assertEqual(
            squared["coordinate_witnesses"]["x"]["return"]["tifloats"]["op1"],
            "008100210000001200",
        )
        self.assertEqual(reciprocal["point_visits"]["error_divide_by_zero"], 2)
        self.assertEqual(reciprocal["integer_line_entries"]["bridges_center"], 0)
        self.assertEqual(reciprocal["error_state_columns"], [46, 47])
        self.assertEqual(reciprocal["sample_columns_before_advance"]["count"], 95)
        self.assertNotIn("0x", " ".join(report["entry_points"].values()))
        self.assertEqual(report["emulator"]["commit"], "d1bdc58dd321ae462a701e556fcb62bb925a78b1")
        self.assertTrue(
            Path(__file__).resolve().with_name("macros").joinpath(
                "graph-y1-reciprocal.macro"
            ).is_file()
        )


if __name__ == "__main__":
    unittest.main()
