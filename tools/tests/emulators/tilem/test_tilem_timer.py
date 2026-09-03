#!/usr/bin/env python3
"""Regression tests for the pinned TilEm timer and RTC probe."""

import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from ti84re.emulators.tilem.timer import (
    TilemTimerError,
    TilemTimerReport,
    build_command,
    expected_timer_report,
    parse_timer_report,
    validate_timer_report,
)

NATIVE_REPORT = " ".join(  # noqa: FLY002 - readable native fixture
    (
        "mode=tilem-timer-probe reset=0,0,0,0,0,0,0,0,0,8,0,0,0,0,0",
        "crystal_us=92,1007,10010,100006,31,488,7813,125000",
        "crystal_count=1,0,1,0,1,0,1,1 cpu_clocks=1,2,4,8,16,32,64",
        "off_running=0,0,0 off_count=5,5,5 mode3_clocks=1,1,1",
        "mode_mask=203,3,200,0",
        "expiry=2,2,8,0,100,100,0,28,0,0,104,4,28,0,0,102,2,28,8,0,107,7,28,8,100",
        "acknowledged=2,2,8,0 restarted=100,0,28,100,1",
        "mapping_status=28,68,E8 mapping_interrupts=8,18,38",
        "source_stop=6,6,0,81,3",
        "rtc=00000000,12345678,12345678,12345682,12345682,12345687,DEADBEEF,DEADBEEF,00000002,DEADBEEF,00FFFFFF,00000000,01000000",
    )
)


class TilemTimerReportTests(unittest.TestCase):
    def test_parser_decodes_complete_native_matrix(self):
        report = parse_timer_report(NATIVE_REPORT)

        self.assertIsInstance(report, TilemTimerReport)
        self.assertEqual((1, 2, 4, 8, 16, 32, 64), report.cpu_clocks)
        self.assertEqual(0xDEADBEEF, report.rtc[7])

    def test_oracle_derives_crystal_rounding_and_counter_readback(self):
        report = expected_timer_report()

        self.assertEqual(
            (92, 1007, 10010, 100006, 31, 488, 7813, 125000),
            report.crystal_us,
        )
        self.assertEqual((1, 0, 1, 0, 1, 0, 1, 1), report.crystal_count)

    def test_mode3_ignores_all_port2f_values(self):
        self.assertEqual((1, 1, 1), expected_timer_report().mode3_clocks)

    def test_expiry_matrix_separates_completion_overflow_and_interrupt(self):
        report = expected_timer_report()
        cases = tuple(report.expiry[index : index + 5] for index in range(0, 25, 5))

        self.assertEqual((0x02, 0x02, 0x08, 0, 0x100), cases[0])
        self.assertEqual((0x100, 0, 0x28, 0, 0), cases[1])
        self.assertEqual((0x104, 0x04, 0x28, 0, 0), cases[2])
        self.assertEqual((0x102, 0x02, 0x28, 0x08, 0), cases[3])
        self.assertEqual((0x107, 0x07, 0x28, 0x08, 0x100), cases[4])

    def test_unacknowledged_nonloop_restart_gets_overflow_period(self):
        self.assertEqual(
            (0x100, 0, 0x28, 0x100, 1),
            expected_timer_report().restarted,
        )

    def test_three_timers_map_to_distinct_status_and_request_bits(self):
        report = expected_timer_report()

        self.assertEqual((0x28, 0x68, 0xE8), report.mapping_status)
        self.assertEqual((0x08, 0x18, 0x38), report.mapping_interrupts)

    def test_source_write_stops_and_retains_current_count(self):
        self.assertEqual((6, 6, 0, 0x81, 3), expected_timer_report().source_stop)

    def test_rtc_oracle_pins_freeze_reset_and_torn_read(self):
        rtc = expected_timer_report().rtc

        self.assertEqual(rtc[3], rtc[4])
        self.assertEqual(0xDEADBEEF, rtc[6])
        self.assertEqual((0x00FFFFFF, 0, 0x01000000), rtc[10:13])

    def test_oracle_accepts_complete_native_matrix(self):
        validated = validate_timer_report(parse_timer_report(NATIVE_REPORT))

        self.assertFalse(validated["source_model"]["rtc_byte_read_latch"])
        self.assertFalse(validated["source_model"]["physical_scope"])

    def test_oracle_rejects_rounded_counter_assumption(self):
        changed = replace(expected_timer_report(), crystal_count=(1,) * 8)
        with self.assertRaisesRegex(TilemTimerError, "disagrees"):
            validate_timer_report(changed)

    def test_parser_rejects_short_rtc_vector(self):
        malformed = NATIVE_REPORT.replace(
            "rtc=00000000,12345678,12345678,12345682,12345682,12345687,DEADBEEF,DEADBEEF,00000002,DEADBEEF,00FFFFFF,00000000,01000000",
            "rtc=00000000",
        )
        with self.assertRaisesRegex(TilemTimerError, "must contain 13"):
            parse_timer_report(malformed)

    @patch("ti84re.emulators.tilem.timer.build_core_command", return_value=["cc", "probe"])
    def test_build_command_adds_shared_support(self, build_core):
        command = build_command(
            Path("/tmp/tilem"),
            Path("tools/probes/tilem/tilem_timer_probe.c"),
            Path("/tmp/tilem-timer-probe"),
        )

        self.assertEqual(["cc", "probe"], command)
        adapters = build_core.call_args.args[1]
        self.assertEqual("tilem_probe_support.c", adapters[0].name)
        self.assertEqual("tilem_timer_probe.c", adapters[1].name)


if __name__ == "__main__":
    unittest.main()
