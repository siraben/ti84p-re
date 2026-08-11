"""Regression tests for the guarded MAME LCD-controller oracle."""

import unittest

from mame_lcd import (
    MameLcdReport,
    expected_mame_lcd_report,
    parse_mame_lcd_report,
    validate_mame_lcd_report,
)
from mame_runtime import MameRuntimeError

NATIVE_OUTPUT = """\
MAME_LCD identity machine=ti84pv3 version=0.287
MAME_LCD reset status10=43 status12=43 port2=C3 ram_nonzero=0 x=00 y=00 z=00 output=00 word=01 display=00 active=01 direction=1
MAME_LCD control rapid_status=63636363 movement_status=60616263 six_status=23 eight_status=63 mirror_off_status=43 mirror_on_status=63 contrast=2F opa1=03 opa2=03 z=3F
MAME_LCD increment cells=A0A1A2A3 final_x=00 final_y=12
MAME_LCD direct column15_cell=B5 column15_final_y=10 column31_cell=BF column31_final_y=00
MAME_LCD latch reads=001234 final_x=02 final_y=03
MAME_LCD six_bit cells=FD50 final_y=02
MAME_LCD mapping delay_initial=00000000000000 delay_patterned=00000000000000 ready=C3
"""


class MameLcdTests(unittest.TestCase):
    def test_parser_decodes_controller_and_port_matrix(self):
        report = parse_mame_lcd_report(NATIVE_OUTPUT)

        self.assertEqual((0x60, 0x61, 0x62, 0x63), report.movement_status)
        self.assertEqual((0xA0, 0xA1, 0xA2, 0xA3), report.increment_cells)
        self.assertEqual((0, 0x12, 0x34), report.latch_reads)
        self.assertEqual((0xFD, 0x50), report.six_cells)

    def test_oracle_reuses_pointer_status_and_latch_models(self):
        result = validate_mame_lcd_report(parse_mame_lcd_report(NATIVE_OUTPUT))

        self.assertEqual(15, result["source_model"]["row_stride"])
        self.assertEqual(15, result["source_model"]["column_15_array_index"])
        self.assertEqual(31, result["source_model"]["column_31_array_index"])
        self.assertFalse(result["source_model"]["unsafe_row63_column31_executed"])

    def test_expected_report_pins_busy_and_mirror_behavior(self):
        report = expected_mame_lcd_report()

        self.assertEqual((0x63,) * 4, report.rapid_status)
        self.assertEqual(0x43, report.mirror_off_status)
        self.assertEqual(0x63, report.mirror_on_status)
        self.assertEqual((0,) * 7, report.delay_patterned)

    def test_parser_rejects_missing_latch_phase(self):
        truncated = NATIVE_OUTPUT.replace(
            "MAME_LCD latch reads=001234 final_x=02 final_y=03\n", ""
        )
        with self.assertRaisesRegex(MameRuntimeError, "latch"):
            parse_mame_lcd_report(truncated)

    def test_parser_rejects_short_delay_block(self):
        malformed = NATIVE_OUTPUT.replace(
            "delay_initial=00000000000000",
            "delay_initial=0000",
        )
        with self.assertRaisesRegex(MameRuntimeError, "delay block"):
            parse_mame_lcd_report(malformed)

    def test_oracle_rejects_sixteen_column_stride(self):
        report = expected_mame_lcd_report()
        changed = MameLcdReport(
            **{
                **report.__dict__,
                "direct_column15_cell": 0,
            }
        )
        with self.assertRaisesRegex(MameRuntimeError, "disagrees"):
            validate_mame_lcd_report(changed)


if __name__ == "__main__":
    unittest.main()
