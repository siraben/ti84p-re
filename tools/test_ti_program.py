#!/usr/bin/env python3
"""Regression tests for deterministic TI program fixture builders."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hardware_probe import decode_ti_variable_file
from ti_program import asm_call_body, asmprgm_body, encode_program_file, filled_program_body


class TiProgramTests(unittest.TestCase):
    def test_builds_assembly_source_and_call_bodies(self):
        self.assertEqual(
            b"\xBB\x6C\x3FC3B59D\x3F",
            asmprgm_body(bytes.fromhex("C3B59D")),
        )
        self.assertEqual(
            b"\xBB\x6A\x5FEMUWF3E\x11\x3F",
            asm_call_body("emuwf3e"),
        )

        with self.assertRaisesRegex(ValueError, "start with a letter"):
            asm_call_body("BAD-NAME")
        with self.assertRaisesRegex(ValueError, "start with a letter"):
            asm_call_body("3BAD")

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
