"""Regression tests for the guarded MAME timer and absent-RTC oracle."""

import unittest

from mame_runtime import MameRuntimeError
from mame_timer import (
    MameTimerReport,
    expected_mame_timer_report,
    parse_mame_timer_report,
    validate_mame_timer_report,
)

NATIVE_OUTPUT = """\
MAME_TIMER identity machine=ti84pv3 version=0.287
MAME_TIMER mapping aux_initial=000000 aux_patterned=000000 rtc_initial=000000000000000000 rtc_patterned=000000000000000000
MAME_TIMER masks setup=FF mode=03 count=00
MAME_TIMER family elapsed_attoseconds=20000000000000000 sources=014181 counts=EAEAEA
MAME_TIMER zero elapsed_frames=15 count=00 setup=07 mode=00 port4=08
MAME_TIMER polarity bit1_set_count=00 bit1_set_setup=00 bit1_set_mode=02 bit1_set_port4=08 bit1_clear_count=00 bit1_clear_setup=00 bit1_clear_mode=00 bit1_clear_port4=88
MAME_TIMER loop count=00 setup=00 mode=00 port4=88
MAME_TIMER global before=68 after=08
MAME_TIMER source_off elapsed_frames=2 count=05 setup=00 mode=02
"""


class MameTimerTests(unittest.TestCase):
    def test_parser_decodes_every_timer_edge(self):
        report = parse_mame_timer_report(NATIVE_OUTPUT)

        self.assertEqual((0x01, 0x41, 0x81), report.family_sources)
        self.assertEqual((0xEA, 0xEA, 0xEA), report.family_counts)
        self.assertEqual(0x88, report.bit1_clear_port4)
        self.assertEqual((0,) * 9, report.rtc_patterned)

    def test_oracle_reuses_source_and_expiry_models(self):
        result = validate_mame_timer_report(parse_mame_timer_report(NATIVE_OUTPUT))

        self.assertEqual(
            "32.768 kHz and low-three-bit divisor",
            result["source_model"]["nonzero_source_family"],
        )
        self.assertFalse(result["source_model"]["counter_zero_expires"])
        self.assertEqual(0x08, result["native"]["global_after"])

    def test_expected_report_pins_immediate_callback_count(self):
        report = expected_mame_timer_report()

        self.assertEqual(20_000_000_000_000_000, report.family_elapsed_attoseconds)
        self.assertEqual((0xEA,) * 3, report.family_counts)

    def test_parser_rejects_missing_phase(self):
        truncated = NATIVE_OUTPUT.replace(
            "MAME_TIMER loop count=00 setup=00 mode=00 port4=88\n", ""
        )
        with self.assertRaisesRegex(MameRuntimeError, "loop"):
            parse_mame_timer_report(truncated)

    def test_parser_rejects_short_rtc_block(self):
        malformed = NATIVE_OUTPUT.replace(
            "rtc_initial=000000000000000000",
            "rtc_initial=0000",
        )
        with self.assertRaisesRegex(MameRuntimeError, "RTC block"):
            parse_mame_timer_report(malformed)

    def test_oracle_rejects_documented_divisor_timing(self):
        report = expected_mame_timer_report()
        changed = MameTimerReport(
            **{
                **report.__dict__,
                "family_counts": (0xEB, 0xEB, 0xEB),
            }
        )

        with self.assertRaisesRegex(MameRuntimeError, "disagrees"):
            validate_mame_timer_report(changed)


if __name__ == "__main__":
    unittest.main()
