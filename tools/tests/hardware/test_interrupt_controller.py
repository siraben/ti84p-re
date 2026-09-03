#!/usr/bin/env python3
"""Regression tests for the reusable interrupt-controller model."""

from fractions import Fraction
import unittest


from ti84re.hardware.interrupt_controller import (
    acknowledge_legacy_sources,
    decode_port03,
    decode_port04_configuration,
    decode_port04_status,
    rom_status_test_order,
    standard_timer_period,
    usb_active_low_sources,
    wabbitemu_standard_timer_period,
)
from ti84re.hardware.describe_interrupt_controller import mask_report, status_report


class InterruptControllerTests(unittest.TestCase):
    def test_normal_os_mask(self):
        mask = decode_port03(0x0B)
        self.assertEqual(("on", "standard_timer_1"), mask.enabled_sources)
        self.assertTrue(mask.keep_power_during_halt)
        self.assertTrue(mask.tilem_programmable_timers_can_wake_halt)

    def test_power_off_mask(self):
        mask = decode_port03(0x11)
        self.assertEqual(("on", "link_activity"), mask.enabled_sources)
        self.assertTrue(mask.low_power_on_halt)
        self.assertFalse(mask.tilem_programmable_timers_can_wake_halt)

    def test_port04_status_separates_on_level(self):
        status = decode_port04_status(0x8B)
        self.assertEqual(
            ("on", "standard_timer_1"),
            status.legacy_pending_sources,
        )
        self.assertEqual(
            ("programmable_timer_3",), status.finished_programmable_timers
        )
        self.assertTrue(status.on_released)

    def test_port04_configuration_fields(self):
        config = decode_port04_configuration(0xC7)
        self.assertTrue(config.paired_mapping)
        self.assertEqual(3, config.standard_timer_index)
        self.assertEqual(3, config.battery_selector)

    def test_documented_timer_periods_are_exact(self):
        self.assertEqual(Fraction(64, 32768), standard_timer_period(0x00, 1))
        self.assertEqual(Fraction(304, 32768), standard_timer_period(0x06, 1))
        self.assertEqual(Fraction(304, 65536), standard_timer_period(0x06, 2))

    def test_wabbitemu_uses_rounded_rate_table(self):
        self.assertEqual(Fraction(1, 512), wabbitemu_standard_timer_period(0x00))
        self.assertEqual(Fraction(1, 227), wabbitemu_standard_timer_period(0x02))
        self.assertEqual(Fraction(1, 158), wabbitemu_standard_timer_period(0x04))
        self.assertEqual(Fraction(1, 108), wabbitemu_standard_timer_period(0x06))
        self.assertEqual(Fraction(1, 216), wabbitemu_standard_timer_period(0x06, 2))

    def test_acknowledgement_clears_only_zeroed_legacy_sources(self):
        pending = 0xF7
        self.assertEqual(0xE0, acknowledge_legacy_sources(pending, 0x08))
        self.assertEqual(0xE1, acknowledge_legacy_sources(pending, 0x09))
        self.assertEqual(0xF7, acknowledge_legacy_sources(pending, 0x17))
        self.assertEqual(0xE8, acknowledge_legacy_sources(0xFF, 0x08))

    def test_cli_reports_include_derived_fields(self):
        self.assertEqual(
            ["on", "standard_timer_1"], mask_report(0x0B)["enabled_sources"]
        )
        report = status_report(0x8B)
        self.assertEqual(
            ["on", "standard_timer_1"], report["legacy_pending_sources"]
        )
        self.assertEqual(
            ["programmable_timer_3"], report["finished_programmable_timers"]
        )

    def test_rom_status_test_priority_ignores_on_level(self):
        self.assertEqual(
            (
                "programmable_timer_3",
                "programmable_timer_1",
                "programmable_timer_2",
                "standard_timer_2",
                "link_activity",
                "on",
                "standard_timer_1",
            ),
            rom_status_test_order(0xFF),
        )
        self.assertEqual((), rom_status_test_order(0x08))

    def test_usb_summary_is_active_low(self):
        self.assertEqual(0, usb_active_low_sources(0x1F))
        self.assertEqual(0x14, usb_active_low_sources(0x0B))

    def test_invalid_values_are_rejected(self):
        with self.assertRaises(ValueError):
            decode_port03(0x100)
        with self.assertRaises(ValueError):
            standard_timer_period(0, 3)


if __name__ == "__main__":
    unittest.main()
