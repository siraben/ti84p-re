#!/usr/bin/env python3
"""Regression tests for the guarded assembled timer-probe CLI."""

import unittest

from run_wabbitemu_timer_physical_probe import validate_decoded_report


def matching_report() -> dict[str, object]:
    return {
        "measurements": {
            "crystal_divisor": {
                "closer_to": "wabbitemu-and-mame-divisor-32"
            },
            "mode3_prescaler": {
                "cases": [
                    {"actual_speed_mode": 0, "closer_to": "equidistant"},
                    {
                        "actual_speed_mode": 1,
                        "closer_to": "emulator-no-prescaler",
                    },
                    {
                        "actual_speed_mode": 1,
                        "closer_to": "emulator-no-prescaler",
                    },
                    {
                        "actual_speed_mode": 1,
                        "closer_to": "emulator-no-prescaler",
                    },
                ]
            },
            "counter_zero": {"closer_to": "wabbitemu-completes-zero"},
            "expiry_status": {"closer_to": "wabbitemu-first-expiry"},
        },
        "restored": {
            "speed": True,
            "power_control": True,
            "port_0x2F": True,
            "timer_1": True,
            "timer_2": True,
            "interrupt_mask": True,
        },
    }


class WabbitemuPhysicalTimerCliTests(unittest.TestCase):
    def test_accepts_complete_wabbitemu_discrimination(self):
        validate_decoded_report(matching_report())

    def test_rejects_missing_mode3_discrimination(self):
        report = matching_report()
        report["measurements"]["mode3_prescaler"]["cases"][1]["closer_to"] = (
            "documented-port-0x2f-prescaler"
        )

        with self.assertRaisesRegex(ValueError, "unexpectedly applied"):
            validate_decoded_report(report)


if __name__ == "__main__":
    unittest.main()
