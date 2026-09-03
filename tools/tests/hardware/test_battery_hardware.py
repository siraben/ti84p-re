#!/usr/bin/env python3
"""Regression tests for battery-comparator and ROM-level models."""

import unittest


from ti84re.hardware.battery import (
    SELECTORS,
    TILEM_THRESHOLDS_TENTHS,
    battery_level,
    battery_model_report,
    comparator_samples,
    modeled_battery_level,
    parse_voltage_tenths,
    threshold_regions,
)


class BatteryHardwareTests(unittest.TestCase):
    def test_rom_decision_tree_covers_all_five_results(self):
        cases = {
            0: "0000",
            1: "1000",
            2: "1100",
            3: "1010",
            4: "1001",
        }
        for expected, bits in cases.items():
            with self.subTest(level=expected):
                samples = {
                    selector: bit == "1"
                    for selector, bit in zip(SELECTORS, bits, strict=True)
                }
                self.assertEqual(expected, battery_level(samples))

    def test_voltage_parser_uses_exact_tenths(self):
        self.assertEqual(36, parse_voltage_tenths("3.6"))
        self.assertEqual(43, parse_voltage_tenths("4.30"))
        for invalid in ("3.65", "-0.1", "25.6", "bad"):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                parse_voltage_tenths(invalid)

    def test_tilem_comparators_follow_source_threshold_table(self):
        self.assertEqual(
            {0x06: True, 0x46: False, 0x86: True, 0xC6: False},
            comparator_samples(36),
        )
        self.assertEqual(3, modeled_battery_level(36))

    def test_tilem_regions_make_level_two_unreachable(self):
        regions = threshold_regions()

        self.assertEqual((None, 33), (regions[0].lower_tenths, regions[0].upper_tenths))
        self.assertEqual((43, None), (regions[-1].lower_tenths, regions[-1].upper_tenths))
        self.assertEqual({0, 1, 3, 4}, {region.level for region in regions})
        self.assertNotIn(2, {region.level for region in regions})

    def test_report_pins_thresholds_and_unreachable_level(self):
        report = battery_model_report()

        self.assertEqual("3.9", report["tilem_threshold_volts"]["0x46"])
        self.assertEqual([2], report["unreachable_levels"])
        self.assertEqual([0, 1, 3, 4], report["reachable_levels"])

    def test_models_require_exact_selector_set(self):
        with self.assertRaisesRegex(ValueError, "exactly four"):
            battery_level({0x06: True})
        with self.assertRaisesRegex(ValueError, "exactly the four"):
            comparator_samples(36, {0x06: 33})
        self.assertEqual(set(SELECTORS), set(TILEM_THRESHOLDS_TENTHS))


if __name__ == "__main__":
    unittest.main()
