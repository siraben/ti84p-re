#!/usr/bin/env python3
"""Regression tests for the pinned TilEm MD5-assist edge probe."""

import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tilem_md5 import (
    TilemMd5Error,
    TilemMd5Report,
    build_command,
    expected_md5_report,
    parse_md5_report,
    validate_md5_report,
)

NATIVE_REPORT = " ".join(  # noqa: FLY002 - readable native fixture
    (
        "mode=tilem-md5-probe reset_operand_reads=00,00,00,00",
        "reset_result=00000000 one_write_result=11000000",
        "three_write_result=33221100 four_write_result=44332211",
        "five_write_result=55443322 masked_controls=1F,3",
        "masked_control_result=00000004 loaded_operand_reads=00,00,00,00",
        "before_mutation_result=D6D117B4 after_mutation_result=343F9701",
        "mixed_result=343F97B4 clock_delta=0",
        "reset_state=0,0,0,0,0,0,0,0,0",
    )
)


class TilemMd5ReportTests(unittest.TestCase):
    def test_parser_decodes_complete_native_matrix(self):
        report = parse_md5_report(NATIVE_REPORT)

        self.assertIsInstance(report, TilemMd5Report)
        self.assertEqual(0x55443322, report.five_write_result)
        self.assertEqual((0x1F, 3), report.masked_controls)

    def test_oracle_reuses_shared_edge_arithmetic(self):
        report = expected_md5_report()

        self.assertEqual(0xD6D117B4, report.before_mutation_result)
        self.assertEqual(0x343F9701, report.after_mutation_result)
        self.assertEqual(0x343F97B4, report.mixed_result)

    def test_oracle_pins_sliding_register_and_control_masks(self):
        report = expected_md5_report()

        self.assertEqual(
            (0x11000000, 0x33221100, 0x44332211, 0x55443322),
            (
                report.one_write_result,
                report.three_write_result,
                report.four_write_result,
                report.five_write_result,
            ),
        )
        self.assertEqual((0x1F, 3), report.masked_controls)

    def test_oracle_pins_zero_latency_and_full_reset(self):
        report = expected_md5_report()

        self.assertEqual(0, report.clock_delta)
        self.assertEqual((0,) * 9, report.reset_state)

    def test_oracle_accepts_complete_native_matrix(self):
        validated = validate_md5_report(parse_md5_report(NATIVE_REPORT))

        self.assertFalse(validated["source_model"]["physical_scope"])
        self.assertIn(
            "shift by 32", validated["source_model"]["shift_zero_c_portability"]
        )

    def test_oracle_rejects_latched_result_assumption(self):
        changed = replace(expected_md5_report(), mixed_result=0xD6D117B4)
        with self.assertRaisesRegex(TilemMd5Error, "disagrees"):
            validate_md5_report(changed)

    def test_parser_rejects_short_reset_state(self):
        malformed = NATIVE_REPORT.replace(
            "reset_state=0,0,0,0,0,0,0,0,0",
            "reset_state=0",
        )
        with self.assertRaisesRegex(TilemMd5Error, "must contain 9"):
            parse_md5_report(malformed)

    @patch("tilem_md5.build_core_command", return_value=["cc", "probe"])
    def test_build_command_adds_shared_support(self, build_core):
        command = build_command(
            Path("/tmp/tilem"),
            Path("tools/tilem_md5_probe.c"),
            Path("/tmp/tilem-md5-probe"),
        )

        self.assertEqual(["cc", "probe"], command)
        adapters = build_core.call_args.args[1]
        self.assertEqual("tilem_probe_support.c", adapters[0].name)
        self.assertEqual("tilem_md5_probe.c", adapters[1].name)


if __name__ == "__main__":
    unittest.main()
