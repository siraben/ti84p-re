#!/usr/bin/env python3
"""Regression tests for the pinned TilEm keypad and ON-edge probe."""

import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from ti84re.emulators.tilem.keypad import (
    TilemKeypadError,
    TilemKeypadReport,
    build_command,
    expected_keypad_report,
    parse_keypad_report,
    validate_keypad_report,
)

NATIVE_REPORT = " ".join(  # noqa: FLY002 - readable native fixture
    (
        "mode=tilem-keypad-probe matrix=FF,FE,FF,FE,FC,F8,7F,FC,FE",
        "group_readback=00,7F,80,FE,FF",
        "scancode=FF,FE,01,01,FF,00,00,00",
        "on=FF,00,01,FF,01,01,00,FF,00,09,08,00",
        "reset=FF,FF,00,00,00,00,00,00,00,00,00,00",
    )
)


class TilemKeypadReportTests(unittest.TestCase):
    def test_parser_decodes_complete_native_matrix(self):
        report = parse_keypad_report(NATIVE_REPORT)

        self.assertIsInstance(report, TilemKeypadReport)
        self.assertEqual((0xFC, 0xF8), report.matrix[4:6])
        self.assertEqual((0x09, 0x08), report.on[9:11])

    def test_oracle_derives_matrix_reads_from_reusable_model(self):
        self.assertEqual(
            (0xFF, 0xFE, 0xFF, 0xFE, 0xFC, 0xF8, 0x7F, 0xFC, 0xFE),
            expected_keypad_report().matrix,
        )

    def test_group_byte_and_row_seven_are_retained(self):
        report = expected_keypad_report()

        self.assertEqual((0x00, 0x7F, 0x80, 0xFE, 0xFF), report.group_readback)
        self.assertEqual(0xFE, report.matrix[-1])

    def test_scancode_mapping_is_immediate_idempotent_and_bounded(self):
        self.assertEqual(
            (0xFF, 0xFE, 1, 1, 0xFF, 0, 0, 0),
            expected_keypad_report().scancode,
        )

    def test_on_is_separate_and_both_transitions_latch(self):
        on = expected_keypad_report().on

        self.assertEqual((0xFF, 1, 0x01), (on[3], on[4], on[5]))
        self.assertEqual((0xFF, 0, 0x09), (on[7], on[8], on[9]))
        self.assertEqual(0, on[11])

    def test_reset_clears_matrix_on_level_and_internal_enable(self):
        self.assertEqual(
            (0xFF, 0xFF) + (0,) * 10,
            expected_keypad_report().reset,
        )

    def test_oracle_accepts_complete_native_matrix(self):
        validated = validate_keypad_report(parse_keypad_report(NATIVE_REPORT))

        self.assertFalse(validated["source_model"]["physical_scope"])
        self.assertEqual("transitive_chain", validated["cases"][5]["name"])

    def test_oracle_rejects_pairwise_closure_assumption(self):
        changed = replace(
            expected_keypad_report(),
            matrix=(0xFF, 0xFE, 0xFF, 0xFE, 0xFC, 0xFC, 0x7F, 0xFC, 0xFE),
        )
        with self.assertRaisesRegex(TilemKeypadError, "disagrees"):
            validate_keypad_report(changed)

    def test_parser_rejects_short_on_vector(self):
        malformed = NATIVE_REPORT.replace(
            "on=FF,00,01,FF,01,01,00,FF,00,09,08,00",
            "on=FF",
        )
        with self.assertRaisesRegex(TilemKeypadError, "must contain 12"):
            parse_keypad_report(malformed)

    @patch("ti84re.emulators.tilem.keypad.build_core_command", return_value=["cc", "probe"])
    def test_build_command_adds_shared_support(self, build_core):
        command = build_command(
            Path("/tmp/tilem"),
            Path("tools/probes/tilem/tilem_keypad_probe.c"),
            Path("/tmp/tilem-keypad-probe"),
        )

        self.assertEqual(["cc", "probe"], command)
        adapters = build_core.call_args.args[1]
        self.assertEqual("tilem_probe_support.c", adapters[0].name)
        self.assertEqual("tilem_keypad_probe.c", adapters[1].name)


if __name__ == "__main__":
    unittest.main()
