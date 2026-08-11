#!/usr/bin/env python3
"""Regression tests for controlled execution of the retail USB ROM."""

import unittest
from dataclasses import fields

from wabbitemu_headless import WabbitemuHeadlessError, WabbitemuUsbRomCaseReport
from wabbitemu_usb_rom import EXPECTED_CASES, validate_usb_rom_reports


def matching_reports() -> tuple[WabbitemuUsbRomCaseReport, ...]:
    common = {
        "boot_steps": 134_845,
        "boot_tstates": 1_746_999,
        "init_visits": 1,
        "reset_helper_visits": 1,
        "violation_resets": 0,
        "flash_changed_bytes": 0,
        "completed": True,
        "source_rom_sha256": "rom-hash",
        "binary_sha256": "binary-hash",
    }
    reports = []
    output_fields = {
        0x4A: "output_4a",
        0x4B: "output_4b",
        0x4C: "output_4c",
        0x54: "output_54",
        0x57: "output_57",
        0x87: "output_87",
        0x89: "output_89",
        0x8B: "output_8b",
        0x92: "output_92",
    }
    for case, expected in EXPECTED_CASES.items():
        writes = expected["writes"]
        values = {**common, **expected, "case": case}
        values.update(
            {
                field: sum(port == expected_port for port, _ in writes)
                for expected_port, field in output_fields.items()
            }
        )
        reports.append(WabbitemuUsbRomCaseReport(**values))
    return tuple(reports)


class WabbitemuUsbRomTests(unittest.TestCase):
    def test_oracle_accepts_all_retail_paths(self):
        result = validate_usb_rom_reports(matching_reports())

        self.assertEqual(4, len(result["cases"]))
        self.assertEqual("2F:52A4", result["rom_entries"]["_InitUSB"])
        self.assertEqual(
            0,
            next(
                case["flash_changed_bytes"]
                for case in result["cases"]
                if case["case"] == "attempt-event-40"
            ),
        )

    def test_oracle_rejects_runtime_drift(self):
        reports = list(matching_reports())
        values = {
            field.name: getattr(reports[0], field.name)
            for field in fields(WabbitemuUsbRomCaseReport)
        }
        values["timeout_tick_visits"] += 1
        reports[0] = WabbitemuUsbRomCaseReport(**values)

        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_usb_rom_reports(tuple(reports))

    def test_oracle_rejects_missing_or_duplicate_case(self):
        reports = matching_reports()

        for incomplete in (reports[:-1], (*reports[:-1], reports[0])):
            with (
                self.subTest(cases=tuple(report.case for report in incomplete)),
                self.assertRaisesRegex(WabbitemuHeadlessError, "incomplete"),
            ):
                validate_usb_rom_reports(incomplete)


if __name__ == "__main__":
    unittest.main()
