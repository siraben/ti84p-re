#!/usr/bin/env python3
"""Regression tests for mapper-overlay emulator evidence."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mapper_probe_evidence import (
    ROOT,
    load_json,
    normalize_exact_run,
    validate_tracked_evidence,
)

FIXTURE = ROOT / "tools" / "fixtures" / "mapper-overlays-emulators.json"


class MapperProbeEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = load_json(FIXTURE)

    def test_tracked_evidence_is_current_and_deterministic(self):
        validate_tracked_evidence(self.evidence)
        expected = json.dumps(self.evidence, indent=2) + "\n"
        self.assertEqual(expected, FIXTURE.read_text(encoding="utf-8"))

    def test_exact_runs_report_numeric_codes_and_full_restoration(self):
        expected = {"tilem": (58756, "tilem"), "wabbitemu": (21062, "wabbitemu")}
        for backend, (code, profile) in expected.items():
            with self.subTest(backend=backend):
                row = self.evidence["emulators"][backend]
                measurements = row["decoded_frame"]["measurements"]
                self.assertEqual("exact-assembled-bytes", row["execution"])
                self.assertEqual(code, row["verification_code_decimal"])
                self.assertEqual(profile, measurements["closest_emulator_profile"])
                self.assertEqual("0x0F", measurements["restore_flags"])
                self.assertTrue(measurements["all_marker_pages_restored"])
                self.assertTrue(measurements["readable_ports_restored"])

    def test_mame_exact_execution_is_distinctly_unsupported(self):
        row = self.evidence["emulators"]["mame"]
        self.assertEqual("unsupported", row["exact_execution"]["status"])
        self.assertEqual("completed", row["direct_handler_profile"]["status"])
        source = row["direct_handler_profile"]["report"]["source_model"]
        self.assertEqual([14, 15, 39, 40], source["unmapped_tested_ports"])
        self.assertFalse(source["forced_ram_overlays"])

    def test_freshness_check_rejects_source_drift(self):
        changed = copy.deepcopy(self.evidence)
        changed["sources"]["tools/hardware-probes/mapper-overlays.asm"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "sources are stale"):
            validate_tracked_evidence(changed)

    def test_freshness_check_rejects_failed_restore(self):
        changed = copy.deepcopy(self.evidence)
        changed["emulators"]["tilem"]["decoded_frame"]["measurements"][
            "all_marker_pages_restored"
        ] = False
        with self.assertRaisesRegex(ValueError, "markers failed"):
            validate_tracked_evidence(changed)

    def test_freshness_check_rejects_wrong_decimal_code(self):
        changed = copy.deepcopy(self.evidence)
        changed["emulators"]["tilem"]["verification_code_decimal"] += 1
        with self.assertRaisesRegex(ValueError, "verification code"):
            validate_tracked_evidence(changed)

    def test_raw_run_cannot_claim_a_different_machine_image(self):
        row = self.evidence["emulators"]["tilem"]
        decoded = copy.deepcopy(row["decoded_frame"])
        raw = {
            "emulator": "TilEm",
            "backend": "tilem",
            "commit": row["commit"],
            "probe": "mapper-overlays",
            "program": "HWPMAP",
            "result_appvar": "HWPMAP01",
            "machine_code_size": row["machine_code_size"],
            "machine_code_sha256": "f" * 64,
            "source_rom_sha256": self.evidence["source_rom_sha256"],
            "decoded_frame": decoded,
            "native_fields": {
                "completed": "1",
                "appvar_matches": "1",
                "display_code": str(row["verification_code_decimal"]),
                "frame_hex": row["frame_hex"],
                "appvar_frame_hex": row["frame_hex"],
            },
            "binary_sha256": row["runner_sha256"],
            "launch": row["launch"],
            "host_intercepts": row["host_intercepts"],
            "evidence_scope": row["evidence_scope"],
        }
        with self.assertRaisesRegex(ValueError, "hash does not match"):
            normalize_exact_run(raw, backend="tilem", artifact=self.evidence["artifact"])


if __name__ == "__main__":
    unittest.main()
