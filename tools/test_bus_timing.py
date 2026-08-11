#!/usr/bin/env python3
"""Regression tests for TI-84 Plus bus-delay decoding."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bus_timing import (
    EMULATOR_PROFILE_KEYS,
    TIMING_PROFILES,
    BusTiming,
    MemoryWaits,
    TimingImplementation,
)


class BusTimingTests(unittest.TestCase):
    def test_os_lcd_access_delays_follow_speed_selected_register(self):
        timing = BusTiming.ti84p_os()

        self.assertEqual([5, 9, 11, 14], [
            timing.lcd_access_wait(mode) for mode in range(4)
        ])

    def test_os_memory_waits_decode_port2e_and_enable_bits(self):
        timing = BusTiming.ti84p_os()
        expected = MemoryWaits(1, 0, 1, 0, 0, 1)

        for mode in range(4):
            self.assertEqual(expected, timing.memory_waits(mode))

    def test_enable_register_can_disable_flash_and_ram_groups(self):
        timing = BusTiming(
            port29=0x00,
            port2a=0x01,
            port2b=0x02,
            port2c=0x03,
            port2e=0x77,
        )

        self.assertEqual(MemoryWaits(0, 0, 0, 0, 0, 0), timing.memory_waits(0))
        self.assertEqual(MemoryWaits(1, 1, 1, 0, 0, 0), timing.memory_waits(1))
        self.assertEqual(MemoryWaits(0, 0, 0, 1, 1, 1), timing.memory_waits(2))
        self.assertEqual(MemoryWaits(1, 1, 1, 1, 1, 1), timing.memory_waits(3))

    def test_os_lcd_ready_fields(self):
        timing = BusTiming.ti84p_os()

        self.assertEqual([0, 240, 176, 176], [
            timing.lcd_ready_hold(mode) for mode in range(4)
        ])
        self.assertEqual([1, 4, 3, 3], [
            timing.documented_mode3_divisor(mode) for mode in range(4)
        ])

    def test_port20_write_selects_low_two_bits(self):
        timing = BusTiming.ti84p_os(speed_mode=0)

        self.assertTrue(timing.write_port(0x20, 0xFF))

        self.assertEqual(3, timing.speed_mode)
        self.assertEqual((0x2C, 0x3B), timing.active_delay_port())

    def test_unrelated_port_is_rejected(self):
        timing = BusTiming.ti84p_os()

        self.assertFalse(timing.write_port(0x21, 0))

    def test_profile_catalog_has_reference_and_three_emulators(self):
        self.assertEqual(
            {"documented", "tilem", "wabbitemu", "mame"},
            set(TIMING_PROFILES),
        )
        self.assertEqual(("tilem", "wabbitemu", "mame"), EMULATOR_PROFILE_KEYS)

    def test_tilem_keeps_four_delay_modes_at_two_cpu_frequencies(self):
        timing = TimingImplementation.ti84p_os("tilem", speed_value=3)

        self.assertEqual(3, timing.read_port(0x20))
        self.assertEqual(15, timing.clock_mhz())
        self.assertEqual((0, 1, 2, 3), timing.selectable_speed_modes())
        self.assertEqual(
            [5, 9, 11, 14],
            [row["lcd_access_wait"] for row in timing.rows()],
        )

    def test_wabbitemu_extra_speed_option_controls_modes_two_and_three(self):
        default = TimingImplementation.ti84p_os("wabbitemu", speed_value=3)
        extra = TimingImplementation.ti84p_os(
            "wabbitemu", speed_value=3, extra_speeds=True
        )

        self.assertEqual(1, default.read_port(0x20))
        self.assertEqual(15, default.clock_mhz())
        self.assertEqual((0, 1), default.selectable_speed_modes())
        self.assertEqual(3, extra.read_port(0x20))
        self.assertEqual(25, extra.clock_mhz())
        self.assertEqual((0, 1, 2, 3), extra.selectable_speed_modes())

    def test_wabbitemu_exposes_port2d_as_a_raw_delay_latch(self):
        timing = TimingImplementation(profile="wabbitemu")

        self.assertTrue(timing.write_port(0x2D, 0xA5))

        self.assertEqual(0xA5, timing.read_port(0x2D))
        self.assertIsNone(TimingImplementation(profile="tilem").read_port(0x2D))

    def test_mame_maps_only_binary_speed_and_ignores_delay_block(self):
        timing = TimingImplementation.ti84p_os("mame", speed_value=0x80)

        self.assertEqual(0x80, timing.read_port(0x20))
        self.assertEqual(1, timing.decoder.speed_mode)
        self.assertEqual(15, timing.clock_mhz())
        self.assertEqual([], timing.rows())
        self.assertEqual(
            [
                (0x29, 0x17),
                (0x2A, 0x27),
                (0x2B, 0x2F),
                (0x2C, 0x3B),
                (0x2E, 0x45),
                (0x2F, 0x4B),
            ],
            timing.ignored_writes,
        )


if __name__ == "__main__":
    unittest.main()
