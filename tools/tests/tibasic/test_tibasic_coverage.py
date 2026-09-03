#!/usr/bin/env python3
"""Regression tests for the bounded TI-BASIC coverage model."""

from __future__ import annotations

import json
import unittest

from ti84re.tibasic.analyze_coverage import (
    TWO_BYTE_LEADS,
    block_transition,
    build_branch_sites,
    build_report,
    finite_models,
    logical_code_point,
)
from ti84re.rom.image import RomImage
from ti84re.paths import ORACLES, DEFAULT_ROM


ROM = DEFAULT_ROM
REPORT = ORACLES / "tibasic/tibasic-coverage.json"


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

    def test_logical_targets_distinguish_fixed_ram_from_banked_flash(self) -> None:
        self.assertEqual(logical_code_point(0x33, 0x2711), ("ram", 0x2711))
        self.assertEqual(logical_code_point(0x33, 0x4381), ("page_33", 0x4381))

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
        self.assertEqual(report["schema"], 2)
        self.assertEqual(report["finite_summary"]["states_exhausted"], 591360)
        self.assertEqual(report["finite_summary"]["semantic_outcomes"], 45)
        self.assertEqual(report["dynamic"]["trace_count"], 33)
        self.assertEqual(report["dynamic"]["branch_outcomes_observed"], 52)
        self.assertEqual(
            report["dynamic"]["branch_outcomes_observed_by_provenance"],
            {
                "internal_entry_probe": 18,
                "natural_tibasic": 38,
                "public_bcall_probe": 8,
            },
        )
        self.assertEqual(
            report["dynamic"]["minimum_outcome_corpus"]["selected_trace_count"],
            15,
        )
        self.assertTrue(report["dynamic"]["minimum_diverse_corpus"]["proven_minimum"])
        self.assertTrue(
            all(len(row["observed"]) == 2 for row in report["dynamic"]["branches"])
        )


if __name__ == "__main__":
    unittest.main()
