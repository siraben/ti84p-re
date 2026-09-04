#!/usr/bin/env python3
"""Regression tests for compact-code cross-emulator evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import subprocess
import unittest
from pathlib import Path
from unittest import mock


from ti84re.hardware import run_compact_probe_e2e as compact_e2e
from ti84re.hardware.run_compact_probe_e2e import run_backend, validate_evidence
from ti84re.paths import ORACLES

FIXTURE = ORACLES / "hardware" / "compact-probe-e2e.json"
LINK_FIXTURE = ORACLES / "hardware" / "compact-probe-link-e2e.json"


class CompactProbeE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.link_evidence = json.loads(LINK_FIXTURE.read_text(encoding="utf-8"))

    def normalized_evidence(self):
        evidence = copy.deepcopy(self.evidence)
        machine_code = b"current assembled machine code"
        evidence["machine_code_size"] = len(machine_code)
        evidence["machine_code_sha256"] = hashlib.sha256(machine_code).hexdigest()
        for backend in ("tilem", "wabbitemu"):
            evidence["backends"][backend]["native_fields"]["probe_size"] = str(
                len(machine_code)
            )
        return evidence, machine_code

    def validate_normalized(self, evidence, machine_code):
        with (
            mock.patch.object(
                compact_e2e,
                "source_hashes",
                return_value=evidence["sources"],
            ),
            mock.patch.object(
                compact_e2e,
                "assemble_machine_code",
                return_value=machine_code,
            ),
        ):
            validate_evidence(evidence)

    def test_tracked_cross_emulator_result_is_current(self):
        validate_evidence(self.evidence)
        validate_evidence(self.link_evidence)

    def test_both_assembly_codes_losslessly_recover_their_frames(self):
        for backend in ("tilem", "wabbitemu"):
            with self.subTest(backend=backend):
                row = self.evidence["backends"][backend]
                self.assertEqual("completed", row["status"])
                self.assertGreater(row["compact_code_length"], 6)
                self.assertEqual(
                    1 + math.ceil(row["compact_code_length"] / 144),
                    row["key_pages"],
                )

    def test_tracked_case_crosses_a_compact_page_boundary(self):
        for backend in ("tilem", "wabbitemu"):
            with self.subTest(backend=backend):
                row = self.evidence["backends"][backend]
                self.assertGreater(row["compact_code_length"], 144)
                self.assertEqual(3, row["key_pages"])

    def test_large_frame_round_trips_past_the_8_bit_length_boundary(self):
        self.assertEqual("link-raw", self.link_evidence["probe"])
        for backend in ("tilem", "wabbitemu"):
            with self.subTest(backend=backend):
                row = self.link_evidence["backends"][backend]
                self.assertGreater(len(bytes.fromhex(row["frame_hex"])), 255)
                self.assertEqual("1", row["native_fields"]["returned"])
        self.assertGreater(
            self.link_evidence["backends"]["wabbitemu"]["compact_code_length"],
            144,
        )

    def test_wabbitemu_exercises_the_real_small_font_renderer(self):
        wabbitemu = self.evidence["backends"]["wabbitemu"]
        tilem = self.evidence["backends"]["tilem"]

        self.assertTrue(wabbitemu["rendered_small_font"])
        self.assertEqual("1", wabbitemu["native_fields"]["rendered"])
        self.assertEqual("1", wabbitemu["native_fields"]["all_pages_nonblank"])
        self.assertEqual("1", wabbitemu["native_fields"]["returned"])
        self.assertEqual("0xFF02", wabbitemu["native_fields"]["final_sp"])
        self.assertFalse(tilem["rendered_small_font"])
        self.assertEqual("0", tilem["native_fields"]["rendered"])
        self.assertEqual("1", tilem["native_fields"]["returned"])
        self.assertEqual("0xFF02", tilem["native_fields"]["final_sp"])

    def test_tampered_render_scope_is_rejected(self):
        changed = copy.deepcopy(self.evidence)
        changed["backends"]["wabbitemu"]["rendered_small_font"] = False

        with self.assertRaises(ValueError):
            validate_evidence(changed)

    def test_tampered_code_is_rejected(self):
        changed = copy.deepcopy(self.evidence)
        changed["backends"]["tilem"]["compact_code"] += "0"

        with self.assertRaises(ValueError):
            validate_evidence(changed)

    def test_tampered_page_count_is_rejected(self):
        changed = copy.deepcopy(self.evidence)
        changed["backends"]["tilem"]["key_pages"] += 1

        with self.assertRaises(ValueError):
            validate_evidence(changed)

    def test_tampered_native_frame_is_rejected(self):
        changed = copy.deepcopy(self.evidence)
        changed["backends"]["wabbitemu"]["native_fields"]["frame_hex"] = "00"

        with self.assertRaises(ValueError):
            validate_evidence(changed)

    def test_strict_native_status_fields_are_required(self):
        cases = (
            ("completed", "0", "completion"),
            ("appvar_matches", "0", "AppVar comparison"),
            ("key_pages", "999", "native pagination"),
            ("probe_id", "255", "native probe ID"),
            ("payload_size", "65535", "native payload size"),
            ("display_code", "0", "native decimal CRC"),
            ("lcd_fnv1a64", "0000000000000000", "native LCD hash"),
        )
        for field, value, message in cases:
            with self.subTest(field=field):
                evidence, machine_code = self.normalized_evidence()
                evidence["backends"]["tilem"]["native_fields"][field] = value
                with self.assertRaisesRegex(ValueError, message):
                    self.validate_normalized(evidence, machine_code)

    def test_machine_hash_must_match_current_assembly(self):
        evidence, machine_code = self.normalized_evidence()
        evidence["machine_code_sha256"] = "0" * 64

        with self.assertRaisesRegex(ValueError, "hash differs from current assembly"):
            self.validate_normalized(evidence, machine_code)

    def test_backend_timeout_is_reported_cleanly(self):
        with mock.patch.object(
            compact_e2e.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="runner", timeout=30),
        ):
            with self.assertRaisesRegex(ValueError, "exceeded 30 seconds"):
                run_backend(
                    backend="tilem",
                    binary=Path("/tmp/not-run-tilem"),
                    rom=Path("/tmp/not-read-rom"),
                    machine_path=Path("/tmp/not-read-probe"),
                    probe_name="asic-snapshot",
                    machine_code=b"",
                )


if __name__ == "__main__":
    unittest.main()
