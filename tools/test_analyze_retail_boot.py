#!/usr/bin/env python3
"""Regression tests for retail-boot layout and trace reduction."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from analyze_retail_boot import (
    BOOT_PAGE,
    BootTraceObservation,
    analyze_boot_page,
    observe_boot_trace,
)
from hardware_trace import ResolvedInstruction
from rom_image import PAGE_SIZE, RomImage


TOOLS = Path(__file__).resolve().parent
REPORT = TOOLS / "retail-boot-traces.json"


def event(index: int, space: str, address: int, *, a: int = 0) -> ResolvedInstruction:
    return ResolvedInstruction(
        instruction_index=index,
        clock=index * 10,
        logical_pc=address,
        space=space,
        address=address,
        flat_address=None,
        page=None,
        physical_page=None,
        opcode=0,
        af=a << 8,
        bc=0,
        de=0,
        hl=0,
        ix=0,
        iy=0,
        sp=0,
        wz=0,
    )


class RetailBootTests(unittest.TestCase):
    def test_partitions_retail_page_and_counts_table_slots(self) -> None:
        data = bytearray(b"\xFF" * (64 * PAGE_SIZE))
        base = BOOT_PAGE * PAGE_SIZE
        data[base : base + 15] = bytes.fromhex(
            "3E07D3043E7FD3063E03D30EC32C81"
        )
        data[base + 0x0F : base + 0x14] = b"1.03\0"
        for identifier, target_page in ((0x8018, 0x3F), (0x80E4, 0x2F)):
            offset = base + (identifier & 0x3FFF)
            data[offset : offset + 3] = bytes((0x45, 0x41, target_page))

        layout = analyze_boot_page(RomImage(bytes(data)))

        self.assertEqual("1.03", layout.version)
        self.assertEqual(87, layout.table_slots)
        self.assertEqual(2, layout.populated_slots)
        self.assertEqual(1, layout.local_targets)
        self.assertEqual(1, layout.external_targets)
        self.assertEqual(434, layout.erased_tail_bytes)

    def test_classifies_boot_dispositions_from_selected_visits(self) -> None:
        cases = {
            "normal": (
                0x00,
                (event(2, "ram", 0x0053),),
                "OS handoff",
            ),
            "mode": (
                0x37,
                (event(2, "ram", 0x0053),),
                "MODE ignored; OS handoff",
            ),
            "del": (
                0x38,
                (event(2, "page_3F", 0x4279),),
                "DEL link recovery",
            ),
            "stat": (
                0x20,
                (event(2, "page_3F", 0x4270),),
                "STAT USB-first recovery",
            ),
        }
        for key, extra, disposition in cases.values():
            with self.subTest(disposition=disposition):
                row = observe_boot_trace(
                    (event(0, "page_3F", 0x4000),)
                    + (event(1, "page_3F", 0x4230, a=key),)
                    + extra
                )
                self.assertIsInstance(row, BootTraceObservation)
                self.assertEqual(disposition, row.disposition)

    def test_checked_report_keeps_four_paths_distinct(self) -> None:
        report = json.loads(REPORT.read_text())
        scenarios = report["scenarios"]

        self.assertEqual("1.03", report["page_layout"]["version"])
        self.assertEqual(87, report["page_layout"]["table_slots"])
        self.assertEqual(87, report["page_layout"]["populated_slots"])
        self.assertEqual(81, report["page_layout"]["local_targets"])
        self.assertEqual(6, report["page_layout"]["external_targets"])
        self.assertEqual(83, report["public_table_names"])
        self.assertEqual(
            ["804E", "8066", "8069", "810B"],
            [row["id"] for row in report["unnamed_entries"]],
        )
        self.assertEqual("OS handoff", scenarios["normal"]["disposition"])
        self.assertEqual("DEL link recovery", scenarios["del"]["disposition"])
        self.assertEqual(
            "STAT USB-first recovery", scenarios["stat"]["disposition"]
        )
        self.assertEqual(
            "MODE ignored; OS handoff",
            scenarios["mode_ignored"]["disposition"],
        )
        self.assertEqual(0, scenarios["del"]["point_visits"]["usb_receive_attempt"])
        self.assertGreater(
            scenarios["stat"]["point_visits"]["usb_receive_attempt"], 0
        )
        self.assertEqual(
            0,
            sum(
                row["point_visits"]["unreferenced_mode_dispatch"]
                for row in scenarios.values()
            ),
        )
        self.assertEqual(
            0,
            sum(
                row["point_visits"]["diagnostic_entry"]
                for row in scenarios.values()
            ),
        )


if __name__ == "__main__":
    unittest.main()
