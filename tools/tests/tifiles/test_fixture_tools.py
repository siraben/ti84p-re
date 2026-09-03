#!/usr/bin/env python3
"""Checks for TI variable-file fixture helpers."""

import tempfile
import unittest

from ti84re.tifiles.build_group_fixture import build_group, entries
from ti84re.trace.make_load_macro import parse_8xp, render_macro
from ti84re.tibasic.samples import PROGRAM_NAMES, SAMPLES as PROGRAM_SAMPLES
from ti84re.paths import TOOLS


SAMPLES = TOOLS / "tibasic-samples"


class FixtureToolTests(unittest.TestCase):
    def test_program_file_parser(self):
        raw = (SAMPLES / "HELLO.8xp").read_bytes()
        var_type, name, body = parse_8xp(raw)
        self.assertEqual((var_type, name), (0x05, "HELLO"))
        self.assertEqual(len(body), 18)
        self.assertEqual(body, raw[74:92])

    def test_program_file_parser_rejects_bad_checksum(self):
        raw = bytearray((SAMPLES / "HELLO.8xp").read_bytes())
        raw[-1] ^= 1
        with self.assertRaisesRegex(SystemExit, "checksum mismatch"):
            parse_8xp(raw)

    def test_load_macro_uses_link_transfer_not_fixed_ram(self):
        fixture = SAMPLES / "HELLO.8xp"
        macro = render_macro(fixture, run_program=True)
        self.assertIn(f"loadvar {fixture.resolve()}", macro)
        self.assertNotIn("poke ", macro)
        self.assertIn("key PRGM", macro)

    def test_zzrun_fixture_uses_its_embedded_labels(self):
        self.assertEqual("OO", PROGRAM_NAMES["ootarget"])
        self.assertEqual("ZZRUN", PROGRAM_NAMES["zzrun"])
        self.assertEqual("ZZRUNWR", PROGRAM_NAMES["zzrunwr"])

        _, body = PROGRAM_SAMPLES["zzrun"]
        machine = bytes.fromhex(bytes(body[3:-1]).decode("ascii"))
        self.assertEqual(81, len(machine))
        self.assertEqual(0x9DDD, int.from_bytes(machine[1:3], "little"))
        self.assertEqual(0xD8, machine[14])  # RET C after _ChkFindSym
        self.assertEqual(0x9DDA, int.from_bytes(machine[63:65], "little"))
        self.assertEqual(b"OK\0\x05OO\0\0\0\0\0\0", machine[-12:])

    def test_group_builder_preserves_entries_and_checksum(self):
        inputs = [SAMPLES / "HELLO.8xp", SAMPLES / "FACTOR.8xp"]
        group, count = build_group(inputs)
        self.assertEqual(count, 2)
        data_length = int.from_bytes(group[53:55], "little")
        self.assertEqual(len(group), 55 + data_length + 2)
        self.assertEqual(
            int.from_bytes(group[-2:], "little"),
            sum(group[55:-2]) & 0xFFFF,
        )
        with tempfile.NamedTemporaryFile(suffix=".8xg") as output:
            output.write(group)
            output.flush()
            self.assertEqual(
                entries(output.name),
                entries(inputs[0]) + entries(inputs[1]),
            )

    def test_group_reader_rejects_bad_checksum(self):
        raw = bytearray((SAMPLES / "HELLO.8xp").read_bytes())
        raw[-1] ^= 1
        with tempfile.NamedTemporaryFile(suffix=".8xp") as damaged:
            damaged.write(raw)
            damaged.flush()
            with self.assertRaisesRegex(ValueError, "checksum mismatch"):
                entries(damaged.name)


if __name__ == "__main__":
    unittest.main()
