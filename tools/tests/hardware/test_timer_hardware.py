#!/usr/bin/env python3
"""Regression tests for timer, ROM-duration, and RTC comparison models."""

import unittest
from fractions import Fraction


from ti84re.hardware.describe_timer import build_parser, report
from ti84re.hardware.timer import (
    APD_COUNTDOWN_SIGNATURE,
    APD_HIGH_RELOAD,
    APD_SETUP_SIGNATURE,
    CURSOR_TOGGLE_TICKS,
    PHYSICAL_TIMER_MEASUREMENT_SIZE,
    TIMER_IMPLEMENTATION_PROFILES,
    decode_physical_timer_measurements,
    decode_timer_source,
    apd_ticks_until_expiry,
    kernel_tick_period,
    os_cadence,
    rom_timer_chunks,
    rom_timer_ticks,
    timer_duration,
    timer_expiry,
    timer_implementation_profile,
)


class TimerHardwareTests(unittest.TestCase):
    def test_apd_signatures_decode_rom_addresses_and_reload(self):
        self.assertEqual(bytes.fromhex("21 49 84 36 74 C9"), APD_SETUP_SIGNATURE)
        self.assertEqual(0x8449, int.from_bytes(APD_SETUP_SIGNATURE[1:3], "little"))
        self.assertEqual(0x74, APD_SETUP_SIGNATURE[4])
        self.assertEqual(APD_SETUP_SIGNATURE[4], APD_HIGH_RELOAD)
        self.assertEqual(
            bytes.fromhex("21 48 84 35 C0 23 35 C0"),
            APD_COUNTDOWN_SIGNATURE,
        )
        self.assertEqual(
            0x8448, int.from_bytes(APD_COUNTDOWN_SIGNATURE[1:3], "little")
        )
        self.assertEqual(0x32, CURSOR_TOGGLE_TICKS)

    def test_apd_phase_range_and_exact_phase(self):
        self.assertEqual(29_441, apd_ticks_until_expiry(1))
        self.assertEqual(29_696, apd_ticks_until_expiry(0))
        self.assertEqual(29_568, apd_ticks_until_expiry(0x80))

        exact = os_cadence("Documented", apd_sub_timer=0x80)
        self.assertEqual(exact.apd_min_ticks, exact.apd_max_ticks)
        self.assertEqual(29_568, exact.apd_min_ticks)

    def test_nominal_os_cadence_is_exact(self):
        cadence = os_cadence("Documented")
        self.assertEqual(Fraction(304, 32_768), cadence.kernel_tick_period_seconds)
        self.assertEqual(Fraction(559_379, 2_048), cadence.apd_min_seconds)
        self.assertEqual(Fraction(551, 2), cadence.apd_max_seconds)
        self.assertEqual(Fraction(3_800, 8_192), cadence.cursor_toggle_seconds)
        self.assertEqual(Fraction(7_600, 8_192), cadence.cursor_cycle_seconds)

    def test_physical_crystal_frequency_scales_documented_profile(self):
        slow = os_cadence("Documented", crystal_hz=32_760)
        nominal = os_cadence("Documented")
        self.assertEqual(Fraction(304, 32_760), slow.kernel_tick_period_seconds)
        self.assertGreater(slow.apd_min_seconds, nominal.apd_min_seconds)
        self.assertIn("measured unit frequency", slow.clock_basis)

    def test_emulator_os_cadence_uses_pinned_scheduler_rates(self):
        tilem = os_cadence("TilEm")
        wabbit = os_cadence("Wabbitemu")
        mame = os_cadence("MAME")
        self.assertEqual(Fraction(9_277, 1_000_000), tilem.kernel_tick_period_seconds)
        self.assertEqual(Fraction(1, 108), wabbit.kernel_tick_period_seconds)
        self.assertEqual(Fraction(1, 256), mame.kernel_tick_period_seconds)
        self.assertEqual(Fraction(273_124_157, 1_000_000), tilem.apd_min_seconds)
        self.assertEqual(Fraction(29_441, 108), wabbit.apd_min_seconds)
        self.assertEqual(Fraction(29_441, 256), mame.apd_min_seconds)

    def test_kernel_tick_rejects_invalid_inputs(self):
        with self.assertRaises(ValueError):
            kernel_tick_period("Documented", crystal_hz=0)
        with self.assertRaises(ValueError):
            kernel_tick_period("unknown")
        with self.assertRaises(ValueError):
            apd_ticks_until_expiry(0x100)

    def test_profiles_are_pinned_and_mame_has_no_rtc(self):
        self.assertEqual(
            4, len({profile.name for profile in TIMER_IMPLEMENTATION_PROFILES})
        )
        self.assertFalse(timer_implementation_profile("mame").rtc_ports)
        self.assertTrue(timer_implementation_profile("public").rtc_ports)
        self.assertEqual("Documented", timer_implementation_profile("nominal").name)
        self.assertEqual("Wabbitemu", timer_implementation_profile("wabbit").name)

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

        cadence_args = parser.parse_args(
            ["os-cadence", "--profile", "Documented", "--apd-sub-timer", "0"]
        )
        cadence = report(cadence_args)["os_cadence"][0]
        self.assertEqual(29_696, cadence["apd_min_ticks"])
        self.assertEqual(cadence["apd_min_ticks"], cadence["apd_max_ticks"])

    def test_rejects_out_of_range_values(self):
        with self.assertRaises(ValueError):
            decode_timer_source("TilEm", 0x100)
        with self.assertRaises(ValueError):
            decode_timer_source("Documented", 0xC0, mode3_prescaler=9)
        with self.assertRaises(ValueError):
            rom_timer_ticks(0x10000)

    def test_decodes_wabbitemu_shaped_physical_timer_matrix(self):
        crystal = bytes((255, 255, 143, 32)) * 4
        mode3 = b"".join(
            bytes(row)
            for row in (
                (0, 0, 254, 64, 250, 52, 34, 1, 8),
                (1, 1, 254, 64, 250, 7, 86, 1, 8),
                (2, 1, 254, 64, 250, 7, 86, 1, 8),
                (3, 1, 254, 64, 250, 7, 86, 1, 8),
            )
        )
        zero = bytes((0, 31, 31, 0, 4, 0x68))
        expiry = bytes((250, 5, 0x68, 240, 5, 0x68))

        report = decode_physical_timer_measurements(
            crystal + mode3 + zero + expiry
        )

        self.assertEqual(
            "wabbitemu-and-mame-divisor-32",
            report["crystal_divisor"]["closer_to"],
        )
        self.assertEqual(
            [
                "equidistant",
                "emulator-no-prescaler",
                "emulator-no-prescaler",
                "emulator-no-prescaler",
            ],
            [
                row["closer_to"]
                for row in report["mode3_prescaler"]["cases"]
            ],
        )
        self.assertEqual(
            "wabbitemu-completes-zero",
            report["counter_zero"]["closer_to"],
        )
        self.assertEqual(
            "wabbitemu-first-expiry",
            report["expiry_status"]["closer_to"],
        )

    def test_decodes_documented_and_tilem_shaped_timer_edges(self):
        crystal = bytes((255, 255, 147, 32)) * 4
        mode3 = b"".join(
            bytes(row)
            for row in (
                (0, 0, 254, 64, 250, 52, 34, 1, 8),
                (1, 1, 254, 64, 250, 64, 21, 1, 8),
                (2, 2, 254, 64, 250, 2, 28, 1, 8),
                (3, 3, 254, 64, 250, 2, 28, 1, 8),
            )
        )
        zero = bytes((0, 31, 31, 16, 0, 0x48))
        expiry = bytes((252, 1, 0x68, 248, 5, 0x68))

        report = decode_physical_timer_measurements(
            crystal + mode3 + zero + expiry
        )

        self.assertEqual(
            "documented-and-tilem-divisor-33",
            report["crystal_divisor"]["closer_to"],
        )
        self.assertEqual(
            "documented-port-0x2f-prescaler",
            report["mode3_prescaler"]["cases"][1]["closer_to"],
        )
        self.assertEqual(
            "documented-and-tilem-free-running-zero",
            report["counter_zero"]["closer_to"],
        )
        self.assertEqual(
            "documented-and-tilem-second-expiry",
            report["expiry_status"]["closer_to"],
        )

    def test_rejects_wrong_physical_timer_measurement_size(self):
        self.assertEqual(64, PHYSICAL_TIMER_MEASUREMENT_SIZE)
        with self.assertRaisesRegex(ValueError, "64 bytes"):
            decode_physical_timer_measurements(bytes(63))


if __name__ == "__main__":
    unittest.main()
