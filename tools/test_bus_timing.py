#!/usr/bin/env python3
"""Regression tests for TI-84 Plus bus-delay decoding."""

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bus_timing import BusTiming, MemoryWaits


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


if __name__ == "__main__":
    unittest.main()
