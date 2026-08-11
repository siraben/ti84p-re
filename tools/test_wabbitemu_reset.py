#!/usr/bin/env python3
"""Regression tests for Wabbitemu reset parsing and source-model checks."""

import unittest

from wabbitemu_headless import (
    WabbitemuHeadlessError,
    WabbitemuResetReport,
    parse_reset_report,
)
from wabbitemu_reset import (
    FRONTEND_RESET_DISPOSITIONS,
    LOW_LEVEL_RESET_DISPOSITIONS,
    RETAINED_COMPONENTS,
    expected_reset_values,
    validate_reset_report,
)


NATIVE_REPORT = " ".join(
    (
        "mode=reset-retention-probe",
        "reset_pc=0x0000 reset_sp=0x0000 reset_imode=1",
        "reset_interrupt=0 reset_ei_block=0 reset_iff1=0 reset_iff2=0",
        "reset_halt=0 reset_io_flags=0 reset_prefix=0",
        "cpu_general_retained=1 reset_ram_lower=0x0000 reset_ram_upper=0x03FF",
        "reset_port27=0 reset_port28=0 reset_boot_mapped=0",
        "reset_page0_changed=0 reset_banks_normal=1 protected_pages_clear=1",
        "reset_pages=3F,00,00,00 reset_page_ram=0,0,0,1",
        "retained=1,1,1,1,1,1,1,1,1,1,1,1,1,1",
        "reset_flash_step=fast-program reset_flash_locked=0 reset_flash_error=1",
        "reset_flash_toggle=0x40 reset_flash_write_byte=0x5A",
        "reset_flash_delay=305419896 reset_flash_lower=0x01CC",
        "reset_flash_upper=0x02DD reset_port24=0xEE reset_prot_mode=3",
        "reset_selectors=12,85,34,56 reset_ram_marker=0xA5",
        "reset_timer_tstates=123456 reset_timer_freq=25000000",
        "reset_timer_version=1 frontend_lcd_active=0 frontend_lcd_x=0",
        "frontend_lcd_y=0 frontend_lcd_z=0 frontend_lcd_contrast=32",
        "frontend_lcd_word_len=8 frontend_lcd_last_read=0x00",
        "frontend_lcd_display_clear=1 frontend_lcd_last_tstate=654321",
        "frontend_lcd_delay=61 frontend_non_lcd_retained=1",
        "program_violation_pc=0x0002 program_violation_af=0x07F5",
        "program_violation_bc=0xB6C6 program_violation_sp=0x0000",
        "program_violation_tstates=7 program_violation_flash_step=read",
        "program_violation_flash_error=0 error_violation_pc=0x0002",
        "error_violation_af=0xE0E5 error_violation_bc=0xC6D6",
        "error_violation_sp=0x0000 error_violation_tstates=7",
        "error_violation_flash_step=error error_violation_flash_error=0",
    )
)


def reset_report(**changes) -> WabbitemuResetReport:
    values = expected_reset_values()
    values.update(changes)
    return WabbitemuResetReport(**values)


class WabbitemuResetTests(unittest.TestCase):
    def test_parser_decodes_seeded_reset_cases(self):
        report = parse_reset_report(NATIVE_REPORT)

        self.assertEqual((0x3F, 0, 0, 0), report.reset_pages)
        self.assertEqual((True,) * 14, report.retained)
        self.assertEqual(0xE0E5, report.error_violation_af)

    def test_parser_rejects_malformed_retention_vector(self):
        malformed = NATIVE_REPORT.replace(
            "retained=1,1,1,1,1,1,1,1,1,1,1,1,1,1",
            "retained=1,1",
        )
        with self.assertRaisesRegex(WabbitemuHeadlessError, "invalid native reset"):
            parse_reset_report(malformed)

    def test_oracle_validates_low_level_frontend_and_violation_results(self):
        result = validate_reset_report(reset_report())

        self.assertEqual(RETAINED_COMPONENTS, result["source_model"]["retained_components"])
        self.assertEqual("read", result["native"]["program_violation_flash_step"])
        self.assertEqual("error", result["native"]["error_violation_flash_step"])

    def test_oracle_rejects_a_reset_that_stops_at_pc_zero(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_reset_report(reset_report(program_violation_pc=0))

    def test_disposition_tables_separate_low_level_and_frontend_reset(self):
        low_level = {entry.disposition for entry in LOW_LEVEL_RESET_DISPOSITIONS}
        frontend_fields = " ".join(entry.fields for entry in FRONTEND_RESET_DISPOSITIONS)

        self.assertEqual({"cleared", "rebuilt", "retained"}, low_level)
        self.assertIn("LCD last_tstate", frontend_fields)
        self.assertEqual(14, len(RETAINED_COMPONENTS))


if __name__ == "__main__":
    unittest.main()
