#!/usr/bin/env python3
"""Regression tests for the pinned TilEm reset probe and source oracle."""

import unittest
from pathlib import Path
from unittest.mock import patch

from ti84re.emulators.tilem.reset import (
    RESET_DISPOSITIONS,
    RESET_GROUPS,
    RETAINED_COMPONENTS,
    TilemResetError,
    TilemResetReport,
    build_command,
    expected_reset_values,
    parse_reset_report,
    validate_reset_report,
)

NATIVE_REPORT = " ".join(  # noqa: FLY002 - readable native report fixture
    (
        "mode=tilem-reset-probe reset_pc=0x8000 reset_sp=0xFFFF",
        "reset_cpu_words_ffff=1 reset_r7=0x80 reset_iff1=0 reset_iff2=0",
        "reset_im=0 reset_interrupts=0x0 reset_halted=0",
        "reset_pages=00,3E,3F,3F reset_speed=6000",
        "reset_ports_match=1 reset_derived_match=1",
        "reset_groups=1,1,1,1,1,1,1,1",
        "retained=1,1,1,1,1,1,1,1,1",
        "reset_flash=0,0,0 reset_lcd=0,32,0,1,0,0,0,7,0,0,16",
        "reset_link=0,0,0,0,0,0,0,0 reset_keypad=255,0,0,1",
        "reset_md5=1,0,0 reset_user_timers=1 retained_clock=123456",
        "retained_dynamic_timer=4321 violation_stop=0x8",
        "violation_exception=0x2 violation_pc=0x8000",
        "violation_af=0xFFFF violation_sp=0xFFFF",
        "violation_pages=00,3E,3F,3F violation_ram_marker=0x5A",
        "violation_flash=0,0,0",
    )
)


def reset_report(**changes) -> TilemResetReport:
    values = expected_reset_values()
    values.update(changes)
    return TilemResetReport(**values)


class TilemResetTests(unittest.TestCase):
    def test_parser_decodes_reset_and_violation_fields(self):
        report = parse_reset_report(NATIVE_REPORT)

        self.assertEqual((0, 0x3E, 0x3F, 0x3F), report.reset_pages)
        self.assertEqual((True,) * 9, report.retained)
        self.assertEqual(0x5A, report.violation_ram_marker)

    def test_parser_rejects_malformed_reset_group_vector(self):
        malformed = NATIVE_REPORT.replace(
            "reset_groups=1,1,1,1,1,1,1,1",
            "reset_groups=1,1",
        )
        with self.assertRaisesRegex(TilemResetError, "invalid native TilEm reset"):
            parse_reset_report(malformed)

    def test_oracle_validates_full_reset_and_post_opcode_ordering(self):
        result = validate_reset_report(reset_report())

        self.assertEqual(RESET_GROUPS, result["source_model"]["reset_groups"])
        self.assertEqual(
            RETAINED_COMPONENTS, result["source_model"]["retained_components"]
        )
        self.assertEqual(0x5A, result["native"]["violation_ram_marker"])
        self.assertEqual(1, len(result["native"]["warnings"]))

    def test_oracle_rejects_fetch_suppression_model(self):
        with self.assertRaisesRegex(TilemResetError, "disagrees"):
            validate_reset_report(reset_report(violation_ram_marker=0))

    def test_dispositions_cover_cleared_rebuilt_and_retained_state(self):
        self.assertEqual(
            {"cleared", "rebuilt", "retained"},
            {entry.disposition for entry in RESET_DISPOSITIONS},
        )

    @patch("ti84re.emulators.tilem.reset.build_core_command", return_value=["cc", "probe"])
    def test_build_command_adds_shared_support(self, build_core):
        command = build_command(
            Path("/tmp/tilem"),
            Path("tools/probes/tilem/tilem_reset_probe.c"),
            Path("/tmp/tilem-reset-probe"),
        )

        self.assertEqual(["cc", "probe"], command)
        adapters = build_core.call_args.args[1]
        self.assertEqual("tilem_probe_support.c", adapters[0].name)
        self.assertEqual("tilem_reset_probe.c", adapters[1].name)


if __name__ == "__main__":
    unittest.main()
