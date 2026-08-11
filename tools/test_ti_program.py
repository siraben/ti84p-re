#!/usr/bin/env python3
"""Regression tests for deterministic TI program fixture builders."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hardware_probe import decode_ti_variable_file
from ti_program import encode_program_file, filled_program_body


class TiProgramTests(unittest.TestCase):
    def test_builds_decodable_program_file(self):
        body = filled_program_body(5, fill_byte=0x31, last_byte=0x3F)

        variable = decode_ti_variable_file(encode_program_file("ZBIGDATA", body))

        self.assertEqual("ZBIGDATA", variable.name)
        self.assertEqual(0x05, variable.variable_type)
        self.assertFalse(variable.archived)
        self.assertEqual(b"\x05\x00\x31\x31\x31\x31\x3F", variable.data)

    def test_builds_exact_cross_page_probe_body(self):
        body = filled_program_body(17_000)

        self.assertEqual(17_000, len(body))
        self.assertEqual(b"\x31" * 16_999 + b"\x3F", body)

    def test_rejects_body_too_large_for_link_format(self):
        with self.assertRaisesRegex(ValueError, "too large"):
            filled_program_body(0xFFFE)


if __name__ == "__main__":
    unittest.main()
