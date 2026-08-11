"""Regression tests for the guarded MAME keypad-matrix oracle."""

import unittest

from mame_keypad import (
    MameKeypadCase,
    MameKeypadReport,
    expected_mame_keypad_report,
    parse_mame_keypad_report,
    validate_mame_keypad_report,
)
from mame_runtime import MameRuntimeError

NATIVE_OUTPUT = """\
MAME_KEYPAD identity machine=ti84pv3 version=0.287
MAME_KEYPAD case name=release_ff mask=FF pressed=0:0 read=FF
MAME_KEYPAD case name=bit7_only mask=7F pressed=0:0 read=FF
MAME_KEYPAD case name=single mask=FE pressed=0:0 read=FE
MAME_KEYPAD case name=unselected mask=FE pressed=1:0 read=FF
MAME_KEYPAD case name=same_column mask=FC pressed=0:0,1:0 read=FF
MAME_KEYPAD case name=rectangle mask=FE pressed=0:0,1:0,1:1 read=FE
MAME_KEYPAD case name=column_seven mask=F7 pressed=3:7 read=7F
MAME_KEYPAD case name=all_selected mask=00 pressed=0:0,1:0,2:1 read=FD
"""


class MameKeypadTests(unittest.TestCase):
    def test_parser_decodes_complete_ordered_matrix(self):
        report = parse_mame_keypad_report(NATIVE_OUTPUT)

        self.assertEqual("ti84pv3", report.machine)
        self.assertEqual(0xFF, report.cases[4].read)
        self.assertEqual(((3, 7),), report.cases[6].pressed_keys)

    def test_oracle_pins_xor_cancellation_and_column_count(self):
        result = validate_mame_keypad_report(parse_mame_keypad_report(NATIVE_OUTPUT))
        native = {case["name"]: case for case in result["native"]["cases"]}

        self.assertEqual(0xFF, native["same_column"]["read"])
        self.assertEqual(0x7F, native["column_seven"]["read"])
        self.assertEqual(8, result["source_model"]["returned_columns"])

    def test_expected_report_reuses_independent_keypad_model(self):
        report = expected_mame_keypad_report()
        reads = {case.name: case.read for case in report.cases}

        self.assertEqual(0xFE, reads["rectangle"])
        self.assertEqual(0xFD, reads["all_selected"])

    def test_parser_rejects_missing_case(self):
        truncated = NATIVE_OUTPUT.rsplit("MAME_KEYPAD case", 1)[0]
        with self.assertRaisesRegex(MameRuntimeError, "incomplete"):
            parse_mame_keypad_report(truncated)

    def test_parser_rejects_changed_selector(self):
        changed = NATIVE_OUTPUT.replace("mask=FC", "mask=FD")
        with self.assertRaisesRegex(MameRuntimeError, "selectors"):
            parse_mame_keypad_report(changed)

    def test_oracle_rejects_union_behavior(self):
        report = expected_mame_keypad_report()
        cases = list(report.cases)
        case = cases[4]
        cases[4] = MameKeypadCase(
            name=case.name,
            group_mask=case.group_mask,
            pressed_keys=case.pressed_keys,
            read=0xFE,
        )
        changed = MameKeypadReport(report.machine, report.version, tuple(cases))

        with self.assertRaisesRegex(MameRuntimeError, "disagrees"):
            validate_mame_keypad_report(changed)


if __name__ == "__main__":
    unittest.main()
