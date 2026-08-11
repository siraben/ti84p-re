"""Regression tests for the guarded MAME MD5-port oracle."""

import unittest

from mame_md5 import (
    MameMd5Report,
    expected_mame_md5_report,
    first_step_expected_result,
    parse_mame_md5_report,
    validate_mame_md5_report,
)
from mame_runtime import MameRuntimeError

NATIVE_OUTPUT = """\
MAME_MD5 identity machine=ti84pv3 version=0.287
MAME_MD5 initial ports=0000000000000000
MAME_MD5 patterned ports=0000000000000000
MAME_MD5 step expected=D6D117B4 observed=00000000 ports=0000000000000000
"""


class MameMd5Tests(unittest.TestCase):
    def test_parser_decodes_all_eight_ports_and_step(self):
        report = parse_mame_md5_report(NATIVE_OUTPUT)

        self.assertEqual((0,) * 8, report.initial_ports)
        self.assertEqual(0xD6D117B4, report.expected_result)
        self.assertEqual(0, report.observed_result)

    def test_independent_model_pins_first_abc_step(self):
        self.assertEqual(0xD6D117B4, first_step_expected_result())

    def test_oracle_accepts_exact_absent_block_behavior(self):
        result = validate_mame_md5_report(expected_mame_md5_report())

        self.assertFalse(result["source_model"]["valid_step_supported"])
        self.assertEqual([], result["source_model"]["mapped_ports"])

    def test_oracle_rejects_retained_patterned_write(self):
        expected = expected_mame_md5_report()
        changed = MameMd5Report(
            **{
                **expected.__dict__,
                "patterned_ports": (0x98,) + expected.patterned_ports[1:],
            }
        )
        with self.assertRaisesRegex(MameRuntimeError, "disagrees"):
            validate_mame_md5_report(changed)

    def test_parser_rejects_missing_step(self):
        incomplete = NATIVE_OUTPUT.split("MAME_MD5 step")[0]
        with self.assertRaisesRegex(MameRuntimeError, "exactly one"):
            parse_mame_md5_report(incomplete)

    def test_parser_rejects_short_port_block(self):
        malformed = NATIVE_OUTPUT.replace(
            "ports=0000000000000000",
            "ports=0000",
            1,
        )
        with self.assertRaisesRegex(MameRuntimeError, "eight bytes"):
            parse_mame_md5_report(malformed)


if __name__ == "__main__":
    unittest.main()
