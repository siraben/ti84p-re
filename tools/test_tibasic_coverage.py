#!/usr/bin/env python3
"""Regression tests for the bounded TI-BASIC coverage model."""

from __future__ import annotations

from pathlib import Path
import json
import unittest

from analyze_tibasic_coverage import (
    TWO_BYTE_LEADS,
    block_transition,
    build_branch_sites,
    build_report,
    finite_models,
)
from rom_image import RomImage


ROOT = Path(__file__).resolve().parents[1]
ROM = ROOT / "tools" / "rom.bin"
REPORT = ROOT / "tools" / "tibasic-coverage.json"


class TiBasicCoverageTests(unittest.TestCase):
    @unittest.skipUnless(ROM.is_file(), "pinned ROM not present")
    def test_two_byte_lead_set_matches_rom_table(self) -> None:
        rom = RomImage.from_path(ROM)
        self.assertEqual(set(rom.bytes_at(0x00, 0x1FF6, 11)), set(TWO_BYTE_LEADS))

    def test_block_transition_boundaries(self) -> None:
        self.assertEqual(block_transition(0, 0xD0, False), "stop_else")
        self.assertEqual(block_transition(1, 0xD0, False), "skip_nested_else")
        self.assertEqual(block_transition(0, 0xD4, False), "stop_end")
        self.assertEqual(block_transition(1, 0xD4, False), "close_nested")
        self.assertEqual(block_transition(0xFFFF, 0xD3, False), "open_loop_wrap")
        self.assertEqual(block_transition(0, 0xCE, False), "single_line_if")
        self.assertEqual(block_transition(0, 0xCE, True), "open_if_then")

    def test_finite_domain_sizes(self) -> None:
        models = {model.name: model for model in finite_models()}
        self.assertEqual(len(models), 8)
        self.assertEqual(len(models["block matcher transition"].inputs), 524288)
        self.assertEqual(len(models["precedence handler family"].inputs), 65536)

    @unittest.skipUnless(ROM.is_file(), "pinned ROM not present")
    def test_declared_branch_sites_are_conditional_rom_instructions(self) -> None:
        sites = build_branch_sites(RomImage.from_path(ROM))
        self.assertEqual(len(sites), 26)
        self.assertEqual(len({site.location for site in sites}), len(sites))
        self.assertTrue(all(site.instruction for site in sites))

    @unittest.skipUnless(ROM.is_file(), "pinned ROM not present")
    def test_report_without_traces_is_stable_and_explicitly_partial(self) -> None:
        report = build_report(ROM, ())
        self.assertEqual(report["finite_summary"]["models"], 8)
        self.assertEqual(report["finite_summary"]["states_exhausted"], 591360)
        self.assertEqual(report["dynamic"]["branch_outcomes_possible"], 52)
        self.assertEqual(report["dynamic"]["branch_outcomes_observed"], 0)
        self.assertIn("not_a_claim", report["scope"])

    def test_checked_report_matches_model_schema(self) -> None:
        report = json.loads(REPORT.read_text())
        self.assertEqual(report["schema"], 1)
        self.assertEqual(report["finite_summary"]["states_exhausted"], 591360)
        self.assertEqual(report["finite_summary"]["semantic_outcomes"], 45)
        self.assertEqual(report["dynamic"]["trace_count"], 6)
        self.assertEqual(report["dynamic"]["branch_outcomes_observed"], 18)
        self.assertTrue(report["dynamic"]["minimum_diverse_corpus"]["proven_minimum"])


if __name__ == "__main__":
    unittest.main()
