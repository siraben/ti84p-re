#!/usr/bin/env python3
"""Regression tests for the pinned TilEm Flash report and oracle."""

import unittest

from tilem_flash import (
    EXPECTED_DIAGNOSTICS,
    TilemFlashError,
    TilemFlashReport,
    expected_flash_values,
    parse_flash_report,
    validate_flash_report,
)

NATIVE_REPORT = " ".join(  # noqa: FLY002 - readable native report fixture
    (
        "mode=tilem-flash-probe flash_size=0x100000 sector_count=19",
        "locked_state=0 locked_byte=0xFF autoselect_state=0",
        "autoselect_byte=0xFF partial_state_before_reset=1",
        "partial_reset_state=0 cfi_state=0 cfi_byte=0xFF",
        "suspend_window_state=6 suspend_state=0 resume_state=0",
        "suspend_changed=0 fast_entry_state=8 fast_first_select_state=9",
        "fast_first_stored=0x50 fast_after_first_state=8",
        "fast_second_select_state=9 fast_second_stored=0xA0",
        "fast_after_second_state=8 fast_exit_select_state=10 fast_exit_state=0",
        "legal_state=0 legal_busy=1 legal_timer=42 legal_stored=0x50",
        "legal_reads=80,C0 legal_final_busy=0 legal_final_read=0x50",
        "illegal_initial_state=7 illegal_initial_busy=1 illegal_timer=42",
        "illegal_stored=0x50 illegal_busy_reads=00,40 illegal_error_state=7",
        "illegal_error_reads=20,60 illegal_reset_state=0 illegal_final_read=0x50",
        "sector_start=0x20000 sector_size=0x10000 sector_state=0",
        "sector_busy=2 sector_wait_timer=300 sector_progaddr=0x20000",
        "sector_erased=65536 sector_changed=65536 sector_outside_changed=0",
        "erase_wait_reads=00,44 erase_busy=3 sector_erase_timer=1200000",
        "erase_busy_reads=08,4C sector_final_busy=0 sector_final_read=0xFF",
        "chip_default_non_ff=81920 chip_default_changed=966656",
        "chip_default_b_byte=0x00 chip_default_boot_byte=0x00",
        "chip_default_state=0 chip_default_busy=2 chip_default_timer=300",
        "chip_default_progaddr=0xFA000 chip_override_non_ff=0",
        "chip_override_changed=1048576 chip_override_boot_byte=0xFF",
        "chip_override_state=0 chip_override_busy=2 chip_override_timer=300",
        "chip_override_progaddr=0xFC000",
    )
)


def flash_report(**changes) -> TilemFlashReport:
    values = expected_flash_values()
    values.update(changes)
    return TilemFlashReport(**values)


class TilemFlashTests(unittest.TestCase):
    def test_parser_decodes_timers_and_status_vectors(self):
        report = parse_flash_report(NATIVE_REPORT)

        self.assertEqual(42, report.legal_timer)
        self.assertEqual((0x00, 0x40), report.illegal_busy_reads)
        self.assertEqual(0x14000, report.chip_default_non_ff)

    def test_parser_rejects_incomplete_report(self):
        with self.assertRaisesRegex(TilemFlashError, "omits"):
            parse_flash_report("mode=tilem-flash-probe flash_size=0x100000")

    def test_oracle_validates_timing_and_protection_boundaries(self):
        result = validate_flash_report(flash_report())

        self.assertEqual(
            1_200_000,
            result["source_model"]["timer_deadlines_at_reset_speed_clocks"]["erase"],
        )
        self.assertEqual(
            [[0xB0000, 0xC0000], [0xFC000, 0x100000]],
            result["source_model"]["default_protected_ranges"],
        )

    def test_oracle_rejects_missing_post_busy_dq5(self):
        with self.assertRaisesRegex(TilemFlashError, "disagrees"):
            validate_flash_report(flash_report(illegal_error_reads=(0x00, 0x40)))

    def test_oracle_requires_exact_native_diagnostics(self):
        with self.assertRaisesRegex(TilemFlashError, "disagrees"):
            validate_flash_report(flash_report(diagnostics=EXPECTED_DIAGNOSTICS[:-1]))


if __name__ == "__main__":
    unittest.main()
