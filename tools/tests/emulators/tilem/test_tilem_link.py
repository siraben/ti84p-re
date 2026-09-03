#!/usr/bin/env python3
"""Regression tests for the pinned TilEm raw-link and assist probe."""

import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from ti84re.emulators.tilem.link import (
    TilemLinkError,
    TilemLinkReport,
    build_command,
    expected_link_report,
    parse_link_report,
    validate_link_report,
)

NATIVE_REPORT = " ".join(  # noqa: FLY002 - readable native fixture
    (
        "mode=tilem-link-probe initial=80,20,0,0,0,0,0,0,0",
        "aux_stored=91,A2,B3,C4 aux_reads=20,0,0,0,0",
        "raw_reads=3,2,1,0,12,12,10,10,21,20,21,20,30,30,30,30",
        "raw_high_write=21 raw_peer=2,1 idle=22,1,22",
        "send_drives=2,1,2,1,1,2,1,2 send=22,1,0,22,0",
        "receive=31,1,A5,20 error=64,1,60,4 clock_delta=0",
        "reset=80,91,A2,B3,C4,0,0,0,0,0,0,0,0,1,0,2,20",
    )
)


class TilemLinkReportTests(unittest.TestCase):
    def test_parser_decodes_complete_native_matrix(self):
        report = parse_link_report(NATIVE_REPORT)

        self.assertIsInstance(report, TilemLinkReport)
        self.assertEqual((0x31, 1, 0xA5, 0x20), report.receive)
        self.assertEqual((0x64, 1, 0x60, 4), report.error)

    def test_oracle_reuses_raw_truth_table_and_byte_order(self):
        report = expected_link_report()

        self.assertEqual((3, 2, 1, 0), report.raw_reads[:4])
        self.assertEqual((2, 1, 2, 1, 1, 2, 1, 2), report.send_drives)

    def test_oracle_pins_tilem_specific_acknowledgements(self):
        report = expected_link_report()

        self.assertEqual((0x22, 1, 0x22), report.idle)
        self.assertEqual((0x22, 1, 0, 0x22, 0), report.send)
        self.assertEqual((0x64, 1, 0x60, 4), report.error)

    def test_oracle_pins_reset_retention_boundary(self):
        reset = expected_link_report().reset

        self.assertEqual((0x91, 0xA2, 0xB3, 0xC4), reset[1:5])
        self.assertEqual(1, reset[13])
        self.assertEqual((0, 2, 0x20), reset[14:17])

    def test_oracle_accepts_complete_native_matrix(self):
        validated = validate_link_report(parse_link_report(NATIVE_REPORT))

        self.assertTrue(validated["source_model"]["raw_activity_interrupt"])
        self.assertFalse(validated["source_model"]["physical_scope"])

    def test_oracle_rejects_wabbitemu_error_clear_assumption(self):
        changed = replace(expected_link_report(), error=(0x4C, 1, 0x0C, 4))
        with self.assertRaisesRegex(TilemLinkError, "disagrees"):
            validate_link_report(changed)

    def test_parser_rejects_short_reset_vector(self):
        malformed = NATIVE_REPORT.replace(
            "reset=80,91,A2,B3,C4,0,0,0,0,0,0,0,0,1,0,2,20",
            "reset=80",
        )
        with self.assertRaisesRegex(TilemLinkError, "must contain 17"):
            parse_link_report(malformed)

    @patch("ti84re.emulators.tilem.link.build_core_command", return_value=["cc", "probe"])
    def test_build_command_adds_shared_support(self, build_core):
        command = build_command(
            Path("/tmp/tilem"),
            Path("tools/probes/tilem/tilem_link_probe.c"),
            Path("/tmp/tilem-link-probe"),
        )

        self.assertEqual(["cc", "probe"], command)
        adapters = build_core.call_args.args[1]
        self.assertEqual("tilem_probe_support.c", adapters[0].name)
        self.assertEqual("tilem_link_probe.c", adapters[1].name)


if __name__ == "__main__":
    unittest.main()
