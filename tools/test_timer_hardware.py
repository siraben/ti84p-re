#!/usr/bin/env python3
"""Regression tests for timer, ROM-duration, and RTC comparison models."""

from fractions import Fraction
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from describe_timer_hardware import build_parser, report
from timer_hardware import (
    TIMER_IMPLEMENTATION_PROFILES,
    decode_timer_source,
    rom_timer_chunks,
    rom_timer_ticks,
    timer_duration,
    timer_expiry,
    timer_implementation_profile,
)


class TimerHardwareTests(unittest.TestCase):
    def test_profiles_are_pinned_and_mame_has_no_rtc(self):
        self.assertEqual(
            4, len({profile.name for profile in TIMER_IMPLEMENTATION_PROFILES})
        )
        self.assertFalse(timer_implementation_profile("mame").rtc_ports)
        self.assertTrue(timer_implementation_profile("public").rtc_ports)

    def test_documented_crystal_divisors_differ_from_wabbitemu_and_mame(self):
        documented = decode_timer_source("documented", 0x41)
        tilem = decode_timer_source("TilEm", 0x41)
        wabbit = decode_timer_source("Wabbitemu", 0x41)
        mame = decode_timer_source("MAME", 0x41)
        self.assertEqual(33, documented.divisor)
        self.assertEqual(33, tilem.divisor)
        self.assertEqual(32, wabbit.divisor)
        self.assertEqual(32, mame.divisor)
        self.assertEqual(Fraction(32768, 33), documented.tick_hz)

    def test_cpu_divisor_priority_matches_emulator_sources(self):
        for profile in ("Documented", "TilEm", "Wabbitemu"):
            with self.subTest(profile=profile):
                self.assertEqual(1, decode_timer_source(profile, 0x80).divisor)
                self.assertEqual(2, decode_timer_source(profile, 0x81).divisor)
                self.assertEqual(64, decode_timer_source(profile, 0xA1).divisor)
        self.assertEqual(3, decode_timer_source("MAME", 0x80).divisor)

    def test_only_documented_profile_applies_mode3_prescaler(self):
        documented = decode_timer_source(
            "Documented", 0xC0, cpu_hz=15_000_000, mode3_prescaler=4
        )
        tilem = decode_timer_source(
            "TilEm", 0xC0, cpu_hz=15_000_000, mode3_prescaler=4
        )
        wabbit = decode_timer_source(
            "Wabbitemu", 0xC0, cpu_hz=15_000_000, mode3_prescaler=4
        )
        self.assertEqual(4, documented.divisor)
        self.assertTrue(documented.port2f_prescaler_applied)
        self.assertEqual(1, tilem.divisor)
        self.assertEqual(1, wabbit.divisor)

    def test_mame_treats_nonzero_off_family_value_as_active(self):
        self.assertIsNone(decode_timer_source("Documented", 0x01))
        self.assertIsNone(decode_timer_source("Wabbitemu", 0x01))
        self.assertEqual(32, decode_timer_source("MAME", 0x01).divisor)

    def test_duration_exposes_mame_zero_delay_first_decrement(self):
        documented = timer_duration("Documented", 0x41, 1)
        tilem = timer_duration("TilEm", 0x41, 1)
        mame = timer_duration("MAME", 0x41, 1)
        self.assertEqual(Fraction(33, 32768), documented.duration_seconds)
        self.assertEqual(Fraction(1007, 1_000_000), tilem.duration_seconds)
        self.assertEqual(0, mame.duration_seconds)
        self.assertEqual(0, mame.scheduled_periods_to_expiry)

    def test_zero_counter_diverges_in_mame(self):
        tilem = timer_duration("TilEm", 0x41, 0)
        mame = timer_duration("MAME", 0x41, 0)
        self.assertTrue(tilem.expires)
        self.assertEqual(256, tilem.effective_counter_ticks)
        self.assertFalse(mame.expires)

    def test_expiry_polarity_and_status_diverge(self):
        tilem = timer_expiry("TilEm", 0x02)
        wabbit = timer_expiry("Wabbitemu", 0x02)
        mame = timer_expiry("MAME", 0x02)
        self.assertTrue(tilem.completion_visible)
        self.assertTrue(tilem.interrupt_generated)
        self.assertFalse(tilem.status_bit2)
        self.assertTrue(wabbit.status_bit2)
        self.assertFalse(mame.completion_visible)
        self.assertFalse(mame.interrupt_generated)

    def test_mame_discards_loop_bit_after_reload(self):
        expiry = timer_expiry("MAME", 0x01)
        self.assertTrue(expiry.counter_reloaded)
        self.assertTrue(expiry.running_after_expiry)
        self.assertEqual(0, expiry.mode_read_after_expiry)
        self.assertTrue(expiry.interrupt_generated)

    def test_halt_suppression_differs_between_tilem_and_wabbitemu(self):
        tilem = timer_expiry(
            "TilEm", 0x02, halted=True, standard_timer_enabled=True
        )
        tilem_without_standard = timer_expiry(
            "TilEm", 0x02, halted=True, standard_timer_enabled=False
        )
        wabbit = timer_expiry("Wabbitemu", 0x02, halted=True)
        self.assertTrue(tilem.interrupt_generated)
        self.assertFalse(tilem_without_standard.interrupt_generated)
        self.assertFalse(wabbit.interrupt_generated)

    def test_rom_duration_uses_radix_255_chunks(self):
        self.assertEqual(255, rom_timer_ticks(0x0100))
        self.assertEqual(256, rom_timer_ticks(0x0101))
        self.assertEqual((255,), rom_timer_chunks(0x0100))
        self.assertEqual((255, 1), rom_timer_chunks(0x0101))
        self.assertEqual((), rom_timer_chunks(0))

    def test_cli_report_is_reusable(self):
        parser = build_parser()
        args = parser.parse_args(
            ["source", "0x41", "--profile", "TilEm", "--profile", "MAME"]
        )
        rows = report(args)["sources"]
        self.assertEqual([33, 32], [row["divisor"] for row in rows])

    def test_rejects_out_of_range_values(self):
        with self.assertRaises(ValueError):
            decode_timer_source("TilEm", 0x100)
        with self.assertRaises(ValueError):
            decode_timer_source("Documented", 0xC0, mode3_prescaler=9)
        with self.assertRaises(ValueError):
            rom_timer_ticks(0x10000)


if __name__ == "__main__":
    unittest.main()
