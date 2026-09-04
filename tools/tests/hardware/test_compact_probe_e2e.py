#!/usr/bin/env python3
"""Regression tests for compact-code cross-emulator evidence."""

from __future__ import annotations

import copy
import json
import math
import unittest


from ti84re.hardware.run_compact_probe_e2e import validate_evidence
from ti84re.paths import ORACLES

FIXTURE = ORACLES / "hardware" / "compact-probe-e2e.json"
LINK_FIXTURE = ORACLES / "hardware" / "compact-probe-link-e2e.json"


class CompactProbeE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.link_evidence = json.loads(LINK_FIXTURE.read_text(encoding="utf-8"))

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


if __name__ == "__main__":
    unittest.main()
