#!/usr/bin/env python3
"""Regression tests for the guarded Wabbitemu Flash-program CLI."""

import argparse
import unittest

from run_wabbitemu_flash_program_probe import (
    FlashProgramCase,
    program_case,
    validate_report,
)
from wabbitemu_headless import WabbitemuFlashProgramReport, WabbitemuHeadlessError


def report(**changes) -> WabbitemuFlashProgramReport:
    values = {
        "target_page": 0x08,
        "target_offset": 0x0100,
        "target_address": 0x4100,
        "target_physical": 0x20100,
        "original_rom_byte": 0xFF,
        "initial": 0x50,
        "requested": 0xD0,
        "configured_flash_locked": False,
        "initial_toggle": 0,
        "command_writes": 4,
        "stored": 0x50,
        "step_after_write": "read",
        "error_after_write": True,
        "toggle_after_write": 0,
        "first_read": 0x20,
        "error_after_first": False,
        "toggle_after_first": 0x40,
        "second_read": 0x50,
        "error_after_second": False,
        "toggle_after_second": 0x40,
        "tstates": 0,
    }
    values.update(changes)
    return WabbitemuFlashProgramReport(**values)


class WabbitemuFlashProgramCliTests(unittest.TestCase):
    def test_parses_case_with_optional_toggle(self):
        self.assertEqual(FlashProgramCase(0x50, 0xD0), program_case("0x50:0xD0"))
        self.assertEqual(
            FlashProgramCase(0x50, 0xD0, 0x40),
            program_case("0x50:0xD0:0x40"),
        )

    def test_rejects_invalid_case(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            program_case("0x50")
        with self.assertRaises(argparse.ArgumentTypeError):
            program_case("0x50:0xD0:1")

    def test_validates_illegal_program_and_one_read_error_lifetime(self):
        result = validate_report(FlashProgramCase(0x50, 0xD0), report())

        self.assertTrue(result["requested_zero_to_one"])
        self.assertEqual(0x20, result["source_model"]["first_read"])
        self.assertEqual(0x50, result["native"]["second_read"])

    def test_rejects_native_disagreement(self):
        with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
            validate_report(
                FlashProgramCase(0x50, 0xD0),
                report(second_read=0x00),
            )

    def test_rejects_unexpected_rom_byte_or_timing(self):
        for changes in ({"original_rom_byte": 0x00}, {"tstates": 1}):
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(WabbitemuHeadlessError, "disagrees"):
                    validate_report(
                        FlashProgramCase(0x50, 0xD0),
                        report(**changes),
                    )


if __name__ == "__main__":
    unittest.main()
