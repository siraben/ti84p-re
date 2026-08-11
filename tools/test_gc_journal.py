#!/usr/bin/env python3
"""Regression tests for archive-GC journal analysis."""

import unittest
from pathlib import Path

from analyze_gc_journal import build_report
from flash_trace import FlashCommand
from gc_journal import (
    analyze_gc_journal,
    GcJournalSignatureError,
    journal_trace_events,
    MASTER_PHASE_OFFSET,
    sector_state_index,
)
from rom_image import RomImage, RomLocation


ROM = Path(__file__).resolve().parent / "rom.bin"


class GcJournalTests(unittest.TestCase):
    def test_sector_state_index_uses_four_page_groups(self):
        self.assertEqual((0, 1, 2, 8), tuple(
            sector_state_index(page) for page in (0x08, 0x0C, 0x10, 0x28)
        ))

    def test_sector_state_index_rejects_non_sector_pages(self):
        for page in (0x04, 0x09, 0x0E):
            with self.subTest(page=page), self.assertRaises(ValueError):
                sector_state_index(page)

    def test_rejects_rom_without_page_3c(self):
        with self.assertRaisesRegex(GcJournalSignatureError, "page 0x3C"):
            analyze_gc_journal(RomImage(bytes(0x4000)))

    def test_rejects_dispatch_signature_mismatch(self):
        rom = RomImage.from_path(ROM)
        data = bytearray(rom.data)
        data[0x3C * 0x4000 + 0x3C1F] ^= 0xFF
        with self.assertRaisesRegex(
            GcJournalSignatureError, "signature mismatch at 3C:7C1F"
        ):
            analyze_gc_journal(RomImage(bytes(data)))

    def test_pinned_rom_reports_layout_and_dispatch(self):
        result = analyze_gc_journal(RomImage.from_path(ROM))

        self.assertEqual(0x1DEA, result.block_offset)
        self.assertEqual(0x66, result.block_length)
        self.assertEqual(
            (0, 1, 2, 3, 4, 5, 6),
            tuple(field.relative_offset for field in result.fields),
        )
        self.assertEqual(
            RomLocation(0x3C, 0x7E99), result.fields[3].helper
        )
        self.assertEqual(
            (0xFF, 0xFE, 0xFC, 0xF8, 0xF0, 0xE0),
            tuple(case.value for case in result.phase_cases),
        )

    def test_pinned_rom_reports_phase_write_sites(self):
        result = analyze_gc_journal(RomImage.from_path(ROM))

        self.assertEqual(
            (0xFE, 0xFC, 0xF8, 0xF0, 0xE0),
            tuple(write.value for write in result.phase_writes),
        )
        self.assertEqual(
            (0x7AD1, 0x7D07, 0x7D12, 0x7D22, 0x7D2D),
            tuple(write.call.address for write in result.phase_writes),
        )

    def test_all_master_transitions_only_clear_bits(self):
        result = analyze_gc_journal(RomImage.from_path(ROM))
        for transition in result.transitions:
            with self.subTest(transition=transition):
                self.assertEqual(
                    transition.destination,
                    transition.source & transition.destination,
                )

    def test_extracts_master_and_sector_trace_events(self):
        commands = (
            FlashCommand(
                "byte_program",
                5,
                50,
                0xFA000 + MASTER_PHASE_OFFSET,
                0xFF,
                (),
            ),
            FlashCommand(
                "byte_program",
                10,
                100,
                0xFA000 + MASTER_PHASE_OFFSET,
                0xFE,
                (),
            ),
            FlashCommand(
                "byte_program",
                20,
                200,
                0xFA000 + 0x1DF0,
                0xFC,
                (),
            ),
            FlashCommand("byte_program", 30, 300, 0x20000, 0xF0, ()),
        )

        events = journal_trace_events(commands)

        self.assertEqual(("master_phase", "sector_state"), tuple(
            event.kind for event in events
        ))
        self.assertEqual((None, 0), tuple(event.sector_index for event in events))

    def test_json_report_keeps_phase_values_numeric(self):
        report = build_report(analyze_gc_journal(RomImage.from_path(ROM)))

        self.assertEqual(0x1DEA, report["block"]["offset"])
        self.assertEqual(0xFF, report["phase_cases"][0]["value"])
        self.assertEqual(0xFE, report["transitions"][0]["destination"])


if __name__ == "__main__":
    unittest.main()
