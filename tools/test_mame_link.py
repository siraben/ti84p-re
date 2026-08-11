"""Regression tests for the guarded MAME raw-link and assist oracle."""

import unittest

from mame_link import (
    MameLinkRawCase,
    expected_mame_link_report,
    parse_mame_link_report,
    validate_mame_link_report,
)
from mame_runtime import MameRuntimeError

NATIVE_OUTPUT = """\
MAME_LINK identity machine=ti84pv3 version=0.287
MAME_LINK raw write=00 read=03 tip_out=1 ring_out=1
MAME_LINK raw write=01 read=12 tip_out=1 ring_out=1
MAME_LINK raw write=02 read=21 tip_out=1 ring_out=1
MAME_LINK raw write=03 read=30 tip_out=1 ring_out=1
MAME_LINK raw write=14 read=07 tip_out=0 ring_out=1
MAME_LINK raw write=28 read=03 tip_out=1 ring_out=0
MAME_LINK raw write=3C read=07 tip_out=0 ring_out=0
MAME_LINK peer pull_low=00 read=03
MAME_LINK peer pull_low=01 read=02
MAME_LINK peer pull_low=02 read=01
MAME_LINK peer pull_low=03 read=00
MAME_LINK assist status=C3 initial=000000000000 patterned=000000000000
"""


class MameLinkTests(unittest.TestCase):
    def test_parser_decodes_raw_connector_and_peer_cases(self):
        report = parse_mame_link_report(NATIVE_OUTPUT)

        self.assertEqual(0x12, report.raw_cases[1].read)
        self.assertEqual(0, report.raw_cases[4].tip_out)
        self.assertEqual(0, report.peer_cases[3].read)

    def test_oracle_accepts_exact_reusable_link_model(self):
        result = validate_mame_link_report(expected_mame_link_report())

        self.assertEqual([9], result["source_model"]["mapped_assist_ports"])
        self.assertFalse(result["source_model"]["assist_operational"])

    def test_expected_normal_writes_release_both_connector_lines(self):
        report = expected_mame_link_report()

        self.assertEqual(
            ((1, 1),) * 4,
            tuple((case.tip_out, case.ring_out) for case in report.raw_cases[:4]),
        )

    def test_oracle_rejects_standard_connector_drive_for_write_one(self):
        expected = expected_mame_link_report()
        cases = list(expected.raw_cases)
        cases[1] = MameLinkRawCase(
            write=0x01,
            read=0x12,
            tip_out=0,
            ring_out=1,
        )
        changed = type(expected)(**{**expected.__dict__, "raw_cases": tuple(cases)})
        with self.assertRaisesRegex(MameRuntimeError, "disagrees"):
            validate_mame_link_report(changed)

    def test_parser_rejects_missing_peer_case(self):
        incomplete = NATIVE_OUTPUT.replace(
            "MAME_LINK peer pull_low=03 read=00\n",
            "",
        )
        with self.assertRaisesRegex(MameRuntimeError, "incomplete peer"):
            parse_mame_link_report(incomplete)

    def test_parser_rejects_short_assist_block(self):
        malformed = NATIVE_OUTPUT.replace(
            "initial=000000000000",
            "initial=0000",
        )
        with self.assertRaisesRegex(MameRuntimeError, "six bytes"):
            parse_mame_link_report(malformed)

    def test_parser_rejects_nonhexadecimal_case_selector(self):
        malformed = NATIVE_OUTPUT.replace("write=14", "write=GG")
        with self.assertRaisesRegex(MameRuntimeError, "case selector"):
            parse_mame_link_report(malformed)


if __name__ == "__main__":
    unittest.main()
