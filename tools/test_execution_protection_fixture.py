#!/usr/bin/env python3
"""Regression tests for guarded Flash execution-protection fixtures."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from execution_protection_fixture import (
    ERASED_TARGET,
    SOURCE_ROM_SHA256,
    TARGET_SIZE,
    RAM_MODE_IMMEDIATE_OFFSET,
    build_ram_execution_probe,
    build_tilem_ram_execution_fixture,
    build_flash_execution_fixture,
    classify_flash_execution,
    file_digest,
    marker_routine,
    ram_marker_routine,
    ram_target_address,
    target_offset,
    validate_probe_machine_code,
    validate_ram_probe_machine_code,
    validate_source_rom,
)
from hardware_probe import decode_ti_variable_file


ROM = Path(__file__).resolve().parent / "rom.bin"


def probe_machine_code(page: int) -> bytes:
    return (
        bytes((0x3E, page, 0xD3, 0x06))
        + bytes.fromhex("21F07F")
        + bytes.fromhex("06061ABE20")
        + bytes.fromhex("3EA0327884")
        + bytes.fromhex("CDF07F")
        + bytes.fromhex("3A788432")
        + bytes.fromhex("327884")
        + bytes.fromhex("D306")
        + marker_routine(page)
    )


def ram_probe_machine_code(page: int, offset: int, marker: int) -> bytes:
    target = ram_target_address(offset)
    return (
        bytes((0x3E, 0x80 | page, 0xD3, 0x06))
        + bytes((0x21, target & 0xFF, target >> 8))
        + bytes.fromhex("06061ABE20")
        + bytes.fromhex("3EA0327884")
        + bytes((0xCD, target & 0xFF, target >> 8))
        + ram_marker_routine(marker)
    )


class ExecutionProtectionFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = ROM.read_bytes()

    def test_patches_only_erased_target_and_packages_programs(self):
        page = 0x08
        machine_code = probe_machine_code(page)
        fixture = build_flash_execution_fixture(self.rom, machine_code, page)
        offset = target_offset(page)

        self.assertEqual(SOURCE_ROM_SHA256, fixture.source_rom_sha256)
        self.assertEqual(ERASED_TARGET, self.rom[offset : offset + TARGET_SIZE])
        self.assertEqual(marker_routine(page), fixture.rom[offset : offset + TARGET_SIZE])
        self.assertEqual(self.rom[:offset], fixture.rom[:offset])
        self.assertEqual(
            self.rom[offset + TARGET_SIZE :],
            fixture.rom[offset + TARGET_SIZE :],
        )
        self.assertEqual("EXECP08", decode_ti_variable_file(fixture.program).name)
        self.assertEqual("AREX08", decode_ti_variable_file(fixture.runner).name)

    def test_call_and_return_addresses_come_from_validated_code(self):
        machine_code = probe_machine_code(0x29)
        call, returned = validate_probe_machine_code(machine_code, 0x29)

        self.assertEqual(call + 3, returned)
        self.assertEqual(call, 0x9D95 + machine_code.index(bytes.fromhex("CDF07F")))

    def test_rejects_wrong_rom_page_and_unguarded_probe(self):
        with self.assertRaisesRegex(ValueError, "exact local"):
            build_flash_execution_fixture(self.rom[:-1], probe_machine_code(8), 8)
        with self.assertRaisesRegex(ValueError, "between"):
            marker_routine(0x40)
        with self.assertRaisesRegex(ValueError, "signature"):
            validate_probe_machine_code(bytes.fromhex("CDF07F"), 8)

    def test_rejects_non_erased_target(self):
        changed = bytearray(self.rom)
        changed[target_offset(8)] = 0

        with self.assertRaisesRegex(ValueError, "exact local"):
            build_flash_execution_fixture(bytes(changed), probe_machine_code(8), 8)

    def test_classifies_return_and_fetch_time_reset_sequences(self):
        self.assertEqual(
            "returned",
            classify_flash_execution(
                call_visits=1,
                target_visits=1,
                target_followup_visits=1,
                return_visits=1,
                resets_after_call=0,
            ),
        )
        self.assertEqual(
            "violation-reset",
            classify_flash_execution(
                call_visits=1,
                target_visits=1,
                target_followup_visits=0,
                return_visits=0,
                resets_after_call=1,
            ),
        )
        self.assertEqual(
            "indeterminate",
            classify_flash_execution(
                call_visits=1,
                target_visits=0,
                target_followup_visits=0,
                return_visits=0,
                resets_after_call=0,
            ),
        )
        self.assertEqual(
            "indeterminate",
            classify_flash_execution(
                call_visits=2,
                target_visits=2,
                target_followup_visits=2,
                return_visits=2,
                resets_after_call=0,
            ),
        )

    def test_streaming_file_digest_rejects_invalid_chunk_size(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "trace"
            path.write_bytes(b"abc")
            self.assertEqual(
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                file_digest(path, chunk_size=2),
            )
            with self.assertRaisesRegex(ValueError, "positive"):
                file_digest(path, chunk_size=0)

    def test_validates_hash_complete_ram_probe(self):
        machine_code = ram_probe_machine_code(5, 0x3FF0, 0x4D)
        probe = build_ram_execution_probe(machine_code, 5, 0x3FF0, 0x4D)

        self.assertEqual(0x85, probe.selector)
        self.assertEqual(0x7FF0, probe.target_address)
        self.assertEqual(probe.call_address + 3, probe.return_address)
        self.assertEqual(
            probe.call_address,
            0x9D95 + machine_code.index(bytes.fromhex("CDF07F")),
        )
        self.assertEqual(64, len(probe.machine_code_sha256))

    def test_rejects_invalid_ram_probe_coordinates_and_sequences(self):
        with self.assertRaisesRegex(ValueError, "between 0 and 7"):
            build_ram_execution_probe(ram_probe_machine_code(0, 0, 0), 8, 0, 0)
        with self.assertRaisesRegex(ValueError, "leave room"):
            ram_target_address(0x3FFF)
        with self.assertRaisesRegex(ValueError, "must be a byte"):
            ram_marker_routine(0x100)
        with self.assertRaisesRegex(ValueError, "target CALL"):
            validate_ram_probe_machine_code(
                ram_probe_machine_code(2, 0x400, 0x42).replace(
                    bytes.fromhex("CD0044"),
                    bytes.fromhex("000000"),
                ),
                2,
                0x400,
                0x42,
            )

    def test_source_rom_guard_is_shared_by_flash_and_ram_fixtures(self):
        self.assertEqual(SOURCE_ROM_SHA256, validate_source_rom(self.rom))
        with self.assertRaisesRegex(ValueError, "exact local"):
            validate_source_rom(self.rom[:-1])

    def test_tilem_ram_fixture_patches_only_the_boot_mode_immediate(self):
        machine_code = ram_probe_machine_code(5, 0x3FF0, 0x4D)
        fixture = build_tilem_ram_execution_fixture(
            self.rom,
            machine_code,
            1,
            5,
            0x3FF0,
            0x4D,
        )

        self.assertEqual(0x10, fixture.rom[RAM_MODE_IMMEDIATE_OFFSET])
        self.assertEqual(
            self.rom[:RAM_MODE_IMMEDIATE_OFFSET],
            fixture.rom[:RAM_MODE_IMMEDIATE_OFFSET],
        )
        self.assertEqual(
            self.rom[RAM_MODE_IMMEDIATE_OFFSET + 1 :],
            fixture.rom[RAM_MODE_IMMEDIATE_OFFSET + 1 :],
        )
        self.assertEqual("RE153FF0", decode_ti_variable_file(fixture.program).name)
        self.assertEqual("AR153FF0", decode_ti_variable_file(fixture.runner).name)


if __name__ == "__main__":
    unittest.main()
