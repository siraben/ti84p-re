#!/usr/bin/env python3
"""Regression tests for deterministic fresh-sector archive fixtures."""

from hashlib import sha256
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from archive_fixture import (
    ARCHIVE_SECTOR_SIZE,
    ArchiveFixtureError,
    build_fresh_archive_fixture,
    encode_archive_record,
)
from build_archive_fixture import parse_program
from hardware_probe import TiVariable
from ti_program import PROGRAM_TYPE, filled_program_body


TOOLS = Path(__file__).resolve().parent


def program(name: str, body_size: int) -> TiVariable:
    body = filled_program_body(body_size)
    return TiVariable(
        variable_type=PROGRAM_TYPE,
        name=name,
        version=0,
        archived=False,
        data=len(body).to_bytes(2, "little") + body,
        comment="fixture",
    )


class ArchiveFixtureTests(unittest.TestCase):
    def test_serializes_observed_archive_record_header(self):
        record = encode_archive_record(program("ZBIGDATA", 17_000), 0x20001)

        self.assertEqual(
            bytes.fromhex("FC7942050000014008085A424947444154416842"),
            record[:20],
        )
        self.assertEqual(17_020, len(record))
        self.assertEqual(b"\x31" * 16_999 + b"\x3F", record[20:])

    def test_places_smaller_record_in_first_sector_gap(self):
        source = b"\xFF" * 0x100000
        fixture = build_fresh_archive_fixture(
            source,
            (
                program("LARGE001", 17_000),
                program("LARGE002", 17_000),
                program("LARGE003", 17_000),
                program("LARGE004", 17_000),
                program("SMALL001", 14_454),
            ),
            (0x20000, 0x30000),
        )

        self.assertEqual(
            (0x20001, 0x2427D, 0x284F9, 0x30001, 0x2C775),
            tuple(record.physical_start for record in fixture.records),
        )
        self.assertEqual(0xF0, fixture.image[0x20000])
        self.assertEqual(0xF0, fixture.image[0x30000])

    def test_rejects_non_erased_sector(self):
        source = bytearray(b"\xFF" * 0x100000)
        source[0x20010] = 0

        with self.assertRaisesRegex(ArchiveFixtureError, "not completely erased"):
            build_fresh_archive_fixture(
                bytes(source),
                (program("TEST", 1),),
                (0x20000,),
            )

    def test_reproduces_record_authentic_f0_seed(self):
        source = (TOOLS / "rom.bin").read_bytes()
        specs = (
            ("ZBIGDATA", 17_000),
            ("YBIGDAT2", 17_000),
            ("XBIGDAT3", 17_000),
            ("WBIGDAT4", 17_000),
            ("VBIGDAT5", 17_000),
            ("UBIGDAT6", 17_000),
            ("TBIGFILL", 14_454),
            ("SBIGFILL", 14_454),
        )

        fixture = build_fresh_archive_fixture(
            source,
            (program(name, size) for name, size in specs),
            (0x20000, 0x30000),
        )

        self.assertEqual(
            "389ed80fe8635740f855c7b8ffec6312a5182027dd0605e8a6e2b094c8481452",
            sha256(fixture.image).hexdigest(),
        )

    def test_parses_program_specification(self):
        self.assertEqual(("ZBIGDATA", 17_000), parse_program("zbigdata=17000"))


if __name__ == "__main__":
    unittest.main()
