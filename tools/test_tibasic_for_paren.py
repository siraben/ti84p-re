"""Regression tests for the compact For( parenthesis trace reducer."""

from __future__ import annotations

import json
from pathlib import Path
import struct
import tempfile
import unittest

from analyze_tibasic_for_paren import analyze_trace, summarize_addresses
from tilem_trace_resolve import HEADER_FMT, INSTR_FMT, MAGIC


REPORT = Path(__file__).resolve().with_name("tibasic-for-paren.json")


def instruction(pc: int, opcode: int, clock: int) -> bytes:
    return b"\x01" + struct.pack(INSTR_FMT, pc, opcode, clock, *([0] * 20))


def memory_write(address: int, value: int) -> bytes:
    return b"\x02" + struct.pack("<IB", address, value)


class TiBasicForParenTests(unittest.TestCase):
    def test_address_summary_recognizes_stride(self) -> None:
        self.assertEqual(
            summarize_addresses([0x9EA9, 0x9EB7, 0x9EC5]),
            {"count": 3, "first": "0x9EA9", "last": "0x9EC5", "stride": 14},
        )

    def test_minimal_trace_reduces_marker_interval_and_buffer_state(self) -> None:
        header = struct.pack(HEADER_FMT, MAGIC, 2, 7, 0, 0xFFFF, 0)
        body = b"".join(
            (
                instruction(0x0001, 0xC9, 100),
                memory_write(0x965D, 0xA9),
                memory_write(0x965E, 0x9E),
                memory_write(0x965F, 0xA9),
                memory_write(0x9660, 0x9E),
                instruction(0x0000, 0x00, 110),
                instruction(0x0001, 0xC9, 200),
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "minimal.trace"
            path.write_bytes(header + body)
            row = analyze_trace(path, marker=("ram", 0x0001, 0xC9))
        self.assertEqual(row["instructions"], 2)
        self.assertEqual(row["clocks"], 100)
        self.assertEqual(row["equal_cursor_end_high_sequence"]["first"], "0x9EA9")

    def test_checked_report_records_reproduced_pair(self) -> None:
        report = json.loads(REPORT.read_text())
        explicit = report["traces"]["explicit_rparen"]
        implicit = report["traces"]["implicit_close"]
        self.assertEqual(explicit["instructions"], 145748)
        self.assertEqual(implicit["instructions"], 157052)
        self.assertEqual(explicit["equal_cursor_end_high_sequence"]["count"], 1)
        self.assertEqual(implicit["equal_cursor_end_high_sequence"]["count"], 25)


if __name__ == "__main__":
    unittest.main()
