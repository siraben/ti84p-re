#!/usr/bin/env python3
"""Regression tests for the complete unlisted-ROM-I/O review manifest."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from port_definitions import load_port_definitions
from rom_image import RomImage
from rom_io_coverage import (
    RETAIL_INDIRECT_REVIEWS,
    RETAIL_REVIEWS,
    CandidateReview,
    audit_indirect_io,
    audit_unlisted_io,
    reconcile_indirect_io,
    reconcile_unlisted_io,
)

TOOLS = Path(__file__).resolve().parent


class RomIOCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = RomImage.from_path(TOOLS / "rom.bin")
        cls.definitions = load_port_definitions(TOOLS / "ports.txt")
        cls.report = audit_unlisted_io(cls.rom, cls.definitions)
        cls.indirect_report = audit_indirect_io(cls.rom)

    def test_exact_retail_manifest_is_complete(self):
        self.assertTrue(self.report.complete)
        self.assertEqual(35, len(self.report.candidates))
        self.assertEqual(
            {"reviewed-data": 34, "operand-overlap": 1},
            self.report.classification_counts,
        )

    def test_missing_review_fails_reconciliation(self):
        report = reconcile_unlisted_io(
            self.rom, self.report.candidates, RETAIL_REVIEWS[:-1]
        )
        self.assertFalse(report.complete)
        self.assertEqual(1, len(report.missing_reviews))

    def test_duplicate_review_fails_reconciliation(self):
        report = reconcile_unlisted_io(
            self.rom,
            self.report.candidates,
            RETAIL_REVIEWS + (RETAIL_REVIEWS[0],),
        )
        self.assertFalse(report.complete)
        self.assertEqual((RETAIL_REVIEWS[0].location,), report.duplicate_review_locations)

    def test_duplicate_candidate_fails_reconciliation(self):
        report = reconcile_unlisted_io(
            self.rom,
            self.report.candidates + (self.report.candidates[0],),
        )
        self.assertFalse(report.complete)
        self.assertEqual(
            (self.report.candidates[0].location,),
            report.duplicate_candidate_locations,
        )

    def test_candidate_fingerprint_drift_fails_reconciliation(self):
        first = RETAIL_REVIEWS[0]
        drifted = CandidateReview(
            first.location,
            b"\xDB\x49",
            "in",
            first.port,
            first.classification,
            first.evidence,
        )
        report = reconcile_unlisted_io(
            self.rom,
            self.report.candidates,
            (drifted,) + RETAIL_REVIEWS[1:],
        )
        self.assertFalse(report.complete)
        self.assertEqual(1, len(report.drift_errors))

    def test_exact_indirect_manifest_is_complete(self):
        report = self.indirect_report
        self.assertTrue(report.complete)
        self.assertEqual(37, len(report.candidates))
        self.assertEqual(2, len(report.resolved))
        self.assertEqual((), report.boundary_prefix_locations)
        self.assertEqual(
            {
                "operand-overlap": 27,
                "resolved-instruction": 2,
                "reviewed-data": 8,
            },
            report.classification_counts,
        )
        self.assertEqual(
            [("37:58A9", "in", 0x48), ("37:5944", "out", 0x44)],
            [
                (str(item.location), item.direction, item.port)
                for item in report.resolved
            ],
        )

    def test_missing_indirect_review_fails_reconciliation(self):
        report = reconcile_indirect_io(
            self.rom,
            self.indirect_report.candidates,
            self.indirect_report.resolved,
            RETAIL_INDIRECT_REVIEWS[:-1],
        )
        self.assertFalse(report.complete)
        self.assertEqual(1, len(report.missing_reviews))

    def test_stale_indirect_review_fails_reconciliation(self):
        report = reconcile_indirect_io(
            self.rom,
            self.indirect_report.candidates[:-1],
            self.indirect_report.resolved,
        )
        self.assertFalse(report.complete)
        self.assertEqual(1, len(report.stale_reviews))

    def test_duplicate_indirect_review_fails_reconciliation(self):
        report = reconcile_indirect_io(
            self.rom,
            self.indirect_report.candidates,
            self.indirect_report.resolved,
            RETAIL_INDIRECT_REVIEWS + (RETAIL_INDIRECT_REVIEWS[0],),
        )
        self.assertFalse(report.complete)
        self.assertEqual(
            (RETAIL_INDIRECT_REVIEWS[0].location,),
            report.duplicate_review_locations,
        )

    def test_duplicate_indirect_candidate_fails_reconciliation(self):
        first = self.indirect_report.candidates[0]
        report = reconcile_indirect_io(
            self.rom,
            self.indirect_report.candidates + (first,),
            self.indirect_report.resolved,
        )
        self.assertFalse(report.complete)
        self.assertEqual((first.location,), report.duplicate_candidate_locations)

    def test_indirect_fingerprint_drift_fails_reconciliation(self):
        first = RETAIL_INDIRECT_REVIEWS[0]
        drifted = replace(first, data=b"\xED\x40", form="IN B,(C)")
        report = reconcile_indirect_io(
            self.rom,
            self.indirect_report.candidates,
            self.indirect_report.resolved,
            (drifted,) + RETAIL_INDIRECT_REVIEWS[1:],
        )
        self.assertFalse(report.complete)
        self.assertEqual(1, len(report.drift_errors))

    def test_indirect_resolution_drift_fails_reconciliation(self):
        first = self.indirect_report.resolved[0]
        report = reconcile_indirect_io(
            self.rom,
            self.indirect_report.candidates,
            (replace(first, port=first.port - 1),)
            + self.indirect_report.resolved[1:],
        )
        self.assertFalse(report.complete)
        self.assertEqual(1, len(report.drift_errors))


if __name__ == "__main__":
    unittest.main()
