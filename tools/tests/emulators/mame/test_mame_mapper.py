"""Regression tests for the guarded MAME memory-mapper oracle."""

import unittest
from dataclasses import replace

from ti84re.emulators.mame.mapper import (
    MameMapperReport,
    expected_mame_mapper_report,
    parse_mame_mapper_report,
    validate_mame_mapper_report,
)
from ti84re.emulators.mame.runtime import MameRuntimeError

NATIVE_OUTPUT = """\
MAME_MAPPER identity case=direct machine=ti84pv3 version=0.287
MAME_MAPPER reset pc=0000 ports=08000000 fixed_before=3E07 a=DB02 b=446F c=DB02 fixed_after=DB02
MAME_MAPPER identity case=independent_b machine=ti84pv3 version=0.287
MAME_MAPPER boot case=independent_b mode=00 bank_a=01 bank_b=02 address=8000 fixed_before=3E07 observed=0E fixed_after=3E07 pc=C008
MAME_MAPPER identity case=window_a machine=ti84pv3 version=0.287
MAME_MAPPER boot case=window_a mode=00 bank_a=01 bank_b=02 address=4000 fixed_before=3E07 observed=44 fixed_after=DB02 pc=C008
MAME_MAPPER identity case=paired_b machine=ti84pv3 version=0.287
MAME_MAPPER boot case=paired_b mode=01 bank_a=02 bank_b=80 address=8001 fixed_before=3E07 observed=02 fixed_after=DB02 pc=C008
MAME_MAPPER identity case=mapping machine=ti84pv3 version=0.287
MAME_MAPPER selectors flash41=446F read41=01 flash7f=3E07 read7f=3F ram80=A0 read80=80 ram86=A6 read86=86 b85=A5 read85=85 cfe=A6 readfe=06
MAME_MAPPER paired a=0E01 b=3E02 c=A3 port5=06 port6=02 port7=83
MAME_MAPPER absent initial=00000000 patterned=00000000
MAME_MAPPER overlay b_before=A2 c_before=D3 forced_b_after=A1 underlying_b_after=E2 forced_c_after=D0 underlying_c_after=E3
MAME_MAPPER fetch marker=22 pc=C303
"""


class MameMapperTests(unittest.TestCase):
    def test_parser_decodes_all_isolated_cases(self):
        report = parse_mame_mapper_report(NATIVE_OUTPUT)

        self.assertEqual((0x3E, 0x07), report.reset_fixed_before)
        self.assertEqual((0xDB, 0x02), report.reset_fixed_after)
        self.assertEqual(0x0E, report.independent_b.observed)
        self.assertEqual(0x44, report.window_a.observed)
        self.assertEqual(0x02, report.paired_b.observed)
        self.assertEqual(0x22, report.fetch_marker)

    def test_source_model_pins_boot_handoff_qualifiers(self):
        report = expected_mame_mapper_report()

        self.assertEqual((0x3E, 0x07), report.independent_b.fixed_after)
        self.assertEqual((0xDB, 0x02), report.window_a.fixed_after)
        self.assertEqual((0xDB, 0x02), report.paired_b.fixed_after)

    def test_source_model_pins_selector_masks_and_adjacent_pair(self):
        report = expected_mame_mapper_report()

        self.assertEqual(0x01, report.selector_read41)
        self.assertEqual(0x3F, report.selector_read7f)
        self.assertEqual(0x06, report.selector_readfe)
        self.assertEqual((0x0E, 0x01), report.paired_a)
        self.assertEqual((0x3E, 0x02), report.paired_b_bytes)

    def test_source_model_pins_absent_overlays_for_reads_writes_and_fetch(self):
        report = expected_mame_mapper_report()

        self.assertEqual((0, 0, 0, 0), report.absent_patterned)
        self.assertEqual(0xA1, report.overlay_forced_b_after)
        self.assertEqual(0xE2, report.overlay_underlying_b_after)
        self.assertEqual(0x22, report.fetch_marker)

    def test_oracle_accepts_exact_native_report(self):
        result = validate_mame_mapper_report(parse_mame_mapper_report(NATIVE_OUTPUT))

        self.assertTrue(result["source_model"]["lua_program_reads_have_side_effects"])
        self.assertFalse(result["source_model"]["unsafe_ram_selector_87_executed"])

    def test_oracle_rejects_independent_b_latch_clear(self):
        expected = expected_mame_mapper_report()
        changed_boot = replace(expected.independent_b, fixed_after=(0xDB, 0x02))
        changed = replace(expected, independent_b=changed_boot)

        with self.assertRaisesRegex(MameRuntimeError, "disagrees"):
            validate_mame_mapper_report(changed)

    def test_oracle_rejects_overlay_fetch_marker(self):
        changed = replace(expected_mame_mapper_report(), fetch_marker=0x11)

        with self.assertRaisesRegex(MameRuntimeError, "disagrees"):
            validate_mame_mapper_report(changed)

    def test_parser_rejects_missing_case(self):
        incomplete = NATIVE_OUTPUT.replace(
            "MAME_MAPPER identity case=paired_b machine=ti84pv3 version=0.287\n",
            "",
        )
        with self.assertRaisesRegex(MameRuntimeError, "five identity"):
            parse_mame_mapper_report(incomplete)

    def test_parser_rejects_short_port_block(self):
        malformed = NATIVE_OUTPUT.replace("ports=08000000", "ports=0800")
        with self.assertRaisesRegex(MameRuntimeError, "exactly 4 bytes"):
            parse_mame_mapper_report(malformed)

    def test_report_remains_typed(self):
        self.assertIsInstance(parse_mame_mapper_report(NATIVE_OUTPUT), MameMapperReport)


if __name__ == "__main__":
    unittest.main()
