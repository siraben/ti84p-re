#!/usr/bin/env python3
"""Regression tests for the pinned TilEm interrupt probe and source model."""

import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from ti84re.hardware.interrupt_controller import TilemLegacyInterruptState
from ti84re.emulators.tilem.interrupt import (
    MASK_VALUES,
    TilemInterruptError,
    TilemInterruptReport,
    build_command,
    expected_interrupt_report,
    parse_interrupt_report,
    validate_interrupt_report,
)

NATIVE_REPORT = " ".join(  # noqa: FLY002 - readable native fixture
    (
        "mode=tilem-interrupt-probe initial_reset=0B,08,0,1,0,0,0,0",
        "reset=0B,08,0,0,0,0,0,0 reset_synced=0B,08,1,1,0,0,0,0",
        "mask_readback=00,01,02,04,08,10,FF mask_on=00,01,00,00,00,00,01",
        "mask_power=00,00,00,00,01,00,01 mask_link=00,00,00,00,00,01,01",
        "mask_no_halt=01,01,00,00,01,01,00 mask_agree=1",
        "ack03_status=E8,E9,EA,EC,E8,F8,FF ack03_other=38,38,38,38,38,38,38",
        "ack02_status=E8,E9,EA,EC,E8,F8,FF ack02_other=38,38,38,38,38,38,38",
        "on_status=00,00,09,08,01,00,09,08,00",
        "timer_status=08,08,08,0A,0C,0C,0E",
        "timer_before=1600,1300,1000 timer_after=1600,1300,1000",
        "timer_periods=1953,1953,1953,4395,4395,4395,6836,6836,6836,9277,9277,9277",
        "link_status=18,08,18,08,08 programmable=302,0,28,102,8,28,302,8,28",
    )
)


class TilemLegacyInterruptStateTests(unittest.TestCase):
    def test_reset_exposes_stored_mask_without_internal_on_enable(self):
        state = TilemLegacyInterruptState()

        self.assertEqual(0x0B, state.port03)
        self.assertFalse(state.on_enabled)
        self.assertEqual(0x08, state.status)

    def test_port_writes_clear_only_zero_legacy_sources(self):
        state = replace(
            TilemLegacyInterruptState(),
            legacy_pending=0x17,
            programmable_finished=0xE0,
        )

        self.assertEqual(0xEA, state.write_port02(0x02).status)
        self.assertEqual(0xF8, state.write_port03(0x10).status)

    def test_on_latches_press_and_release_edges(self):
        state = TilemLegacyInterruptState().sample_on(True).write_port03(1)
        self.assertEqual(0x00, state.status)

        released = state.sample_on(False)
        self.assertEqual(0x09, released.status)
        pressed = released.write_port02(0xFE).sample_on(True)
        self.assertEqual(0x01, pressed.status)

    def test_timer_and_link_callbacks_require_their_masks(self):
        state = TilemLegacyInterruptState().write_port03(0x16)

        observed = state.standard_timer_tick(1).standard_timer_tick(2)
        observed = observed.link_transition()
        self.assertEqual(0x1E, observed.status)

    def test_state_rejects_unknown_pending_bits(self):
        with self.assertRaisesRegex(ValueError, "unknown bits"):
            TilemLegacyInterruptState(legacy_pending=0x08)


class TilemInterruptReportTests(unittest.TestCase):
    def test_parser_decodes_complete_native_matrix(self):
        report = parse_interrupt_report(NATIVE_REPORT)

        self.assertIsInstance(report, TilemInterruptReport)
        self.assertEqual(MASK_VALUES, report.mask_readback)
        self.assertEqual((1600, 1300, 1000), report.timer_before)
        self.assertEqual(0x302, report.programmable[0])

    def test_source_oracle_pins_reset_mismatch_and_both_timer2_callbacks(self):
        report = expected_interrupt_report()

        self.assertEqual((0x0B, 0x08, 0, 0, 0, 0, 0, 0), report.reset)
        self.assertEqual((0x0C, 0x0C), report.timer_status[4:6])
        self.assertEqual(report.timer_before, report.timer_after)

    def test_oracle_accepts_complete_native_matrix(self):
        validated = validate_interrupt_report(parse_interrupt_report(NATIVE_REPORT))

        self.assertEqual(2, validated["source_model"]["timer2_callbacks"])
        self.assertFalse(validated["source_model"]["physical_scope"])

    def test_oracle_rejects_press_only_on_policy(self):
        changed = replace(expected_interrupt_report(), on_status=(0,) * 9)
        with self.assertRaisesRegex(TilemInterruptError, "disagrees"):
            validate_interrupt_report(changed)

    def test_parser_rejects_short_period_vector(self):
        malformed = NATIVE_REPORT.replace(
            "timer_periods=1953,1953,1953,4395,4395,4395,6836,6836,6836,9277,9277,9277",
            "timer_periods=1953",
        )
        with self.assertRaisesRegex(TilemInterruptError, "must contain 12"):
            parse_interrupt_report(malformed)

    @patch("ti84re.emulators.tilem.interrupt.build_core_command", return_value=["cc", "probe"])
    def test_build_command_adds_shared_support(self, build_core):
        command = build_command(
            Path("/tmp/tilem"),
            Path("tools/probes/tilem/tilem_interrupt_probe.c"),
            Path("/tmp/tilem-interrupt-probe"),
        )

        self.assertEqual(["cc", "probe"], command)
        adapters = build_core.call_args.args[1]
        self.assertEqual("tilem_probe_support.c", adapters[0].name)
        self.assertEqual("tilem_interrupt_probe.c", adapters[1].name)


if __name__ == "__main__":
    unittest.main()
