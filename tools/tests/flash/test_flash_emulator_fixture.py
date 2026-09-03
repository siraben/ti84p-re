#!/usr/bin/env python3
"""Regression tests for the emulator-only WriteFlash crossing fixture."""

import hashlib
import unittest


from ti84re.flash.emulator_fixture import (
    FLASH_FIXTURES,
    ENTRY_SIGNATURE_CHECK,
    ERASECERTIFICATESECTOR_BCALL,
    ERASEFLASHPAGE_BCALL,
    PATCH_COMPARE_LOOP,
    PATCH_SIGNATURE_CHECK,
    SOURCE_ROM_SHA256,
    UNLOCK_RETURN_OFFSET,
    UNLOCK_RETURN_ORIGINAL,
    UNLOCK_RETURN_PATCHED,
    WRITEABYTE_BCALL,
    WRITEABYTE_SAFE_BCALL,
    WRITEFLASH_UNSAFE_BCALL,
    WRITEFLASH_BCALL,
    build_crossing_fixture,
    build_fixture,
    patch_unlock_return,
    validate_crossing_machine_code,
)
from ti84re.hardware.probe import decode_ti_variable_file
from ti84re.paths import DEFAULT_ROM


ROM = DEFAULT_ROM


def fixture_machine_code() -> bytes:
    return (
        PATCH_SIGNATURE_CHECK
        + PATCH_COMPARE_LOOP
        + bytes.fromhex("3e3d11ff7f010200")
        + WRITEFLASH_UNSAFE_BCALL
        + bytes.fromhex("40e0")
    )


def error_fixture_machine_code() -> bytes:
    return (
        PATCH_SIGNATURE_CHECK
        + PATCH_COMPARE_LOOP
        + bytes.fromhex("3e3d11ff7f010100")
        + WRITEFLASH_UNSAFE_BCALL
        + bytes.fromhex("d0f5e13e3dd3063aff7f32")
    )


def certificate_program_error_machine_code() -> bytes:
    return (
        PATCH_SIGNATURE_CHECK
        + bytes.fromhex("06081abec2")
        + bytes.fromhex("210a73060c1abec2")
        + bytes.fromhex("21797306121abec2")
        + bytes.fromhex("3e3ed3063a0040b7")
        + bytes.fromhex("3e3dd306210a73110081018100edb0")
        + bytes.fromhex("afd3063e3e110040010100")
        + bytes.fromhex("cd0081f5e1")
        + bytes.fromhex("db0632")
        + bytes.fromhex("3e3ed3063a004032")
        + bytes.fromhex("3e3cd306cdd566")
    )


def entry_returns_machine_code() -> bytes:
    return (
        ENTRY_SIGNATURE_CHECK
        + PATCH_COMPARE_LOOP
        + bytes.fromhex("e3cb7ce3c0e63ffe")
        + bytes.fromhex("3e7e110040010100")
        + WRITEFLASH_BCALL
        + bytes.fromhex("3e7f110040010100")
        + WRITEFLASH_UNSAFE_BCALL
        + bytes.fromhex("3e7d110040010000")
        + WRITEFLASH_UNSAFE_BCALL
        + bytes.fromhex("cda64c")
    )


def byte_entry_returns_machine_code() -> bytes:
    return (
        bytes.fromhex("219a4c06101abec2")
        + bytes.fromhex("e63ffe3ec821788470010100e3cb7ce3")
        + bytes.fromhex("3e7e013322115544217766")
        + WRITEABYTE_SAFE_BCALL
        + bytes.fromhex("3e7f015544117766219988")
        + WRITEABYTE_SAFE_BCALL
        + bytes.fromhex("3e7f01665511887721aa99")
        + WRITEABYTE_BCALL
        + bytes.fromhex("373ea501776611998821bbaa")
        + bytes.fromhex("cd9f4c")
        + bytes.fromhex("3a788432") * 5
        + bytes.fromhex("327884") * 2
    )


def locked_byte_noop_machine_code() -> bytes:
    return (
        bytes.fromhex("219a4c21d56606101abec0")
        + bytes.fromhex("e63ffe3ec821788470010100e3cb7ce3")
        + bytes.fromhex("00000000f5af00f30000ed56f3d314f3")
        + bytes.fromhex("3e3dd3063aff7ffe50")
        + bytes.fromhex("cdd566db02e604c2")
        + bytes.fromhex("3e3d11ff7f06400e99")
        + WRITEABYTE_BCALL
        + bytes.fromhex("3e3dd3063aff7f32")
        + bytes.fromhex("3a788432") * 2
        + bytes.fromhex("327884")
    )


def low_source_cross_machine_code() -> bytes:
    return (
        bytes.fromhex("21680021ca4c21d566")
        + bytes.fromhex("4d50")
        + bytes.fromhex("e63fd306cb7c2004fdcb25cefdcb254e")
        + bytes.fromhex("00000000f5af00f30000ed56f3d314f3")
        + bytes.fromhex("cb8e")
        + bytes.fromhex("3e3d11ff7f010200216800")
        + WRITEFLASH_UNSAFE_BCALL
        + bytes.fromhex("3a008032") * 2
        + bytes.fromhex("320080")
        + bytes.fromhex("cdd566")
    )


def erase_entry_returns_machine_code() -> bytes:
    return (
        bytes.fromhex("211e4c212a4c213f4e")
        + bytes.fromhex("06081abec0")
        + bytes.fromhex("210040e63ffe3ec8")
        + bytes.fromhex("e3cb7ce3c0dde5dd")
        + bytes.fromhex("f57cee40fe002809")
        + ERASEFLASHPAGE_BCALL
        + ERASECERTIFICATESECTOR_BCALL
        + bytes.fromhex("cd2a4c")
    )


def certificate_erase_success_machine_code() -> bytes:
    return (
        PATCH_SIGNATURE_CHECK
        + PATCH_COMPARE_LOOP
        + bytes.fromhex("af373ea5210040")
        + ERASECERTIFICATESECTOR_BCALL
        + bytes.fromhex("f5e13e3ed3063a004032")
    )


def erase_busy_range_machine_code() -> bytes:
    return (
        PATCH_SIGNATURE_CHECK
        + PATCH_COMPARE_LOOP
        + bytes.fromhex("cd5870")
        + bytes.fromhex("3e02d3063eaa32aa6a")
        + bytes.fromhex("3e01d3063e55325555")
        + bytes.fromhex("3e02d3063e8032aa6a")
        + bytes.fromhex("3e02d3063eaa32aa6a")
        + bytes.fromhex("3e01d3063e55325555")
        + bytes.fromhex("3e3ed3063e30320040")
        + bytes.fromhex("3a0040cb5f283a0040")
        + bytes.fromhex("3aff5f3a0060") * 2
        + bytes.fromhex("3e3dd3063aff7f") * 2
        + bytes.fromhex("3e3fd3063a0040") * 2
        + bytes.fromhex("3e08d3063a0040") * 2
        + bytes.fromhex("3e3ed3063a0040cb7f28")
        + bytes.fromhex("3e3cd306cdd566")
    )


class FlashEmulatorFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rom = ROM.read_bytes()

    def test_patch_is_exact_and_does_not_mutate_source(self):
        patched = patch_unlock_return(self.rom)
        end = UNLOCK_RETURN_OFFSET + len(UNLOCK_RETURN_PATCHED)

        self.assertEqual(
            SOURCE_ROM_SHA256,
            hashlib.sha256(self.rom).hexdigest(),
        )
        self.assertEqual(UNLOCK_RETURN_ORIGINAL, self.rom[UNLOCK_RETURN_OFFSET:end])
        self.assertEqual(UNLOCK_RETURN_PATCHED, patched[UNLOCK_RETURN_OFFSET:end])
        self.assertEqual(
            self.rom[:UNLOCK_RETURN_OFFSET],
            patched[:UNLOCK_RETURN_OFFSET],
        )
        self.assertEqual(self.rom[end:], patched[end:])

    def test_rejects_wrong_rom_and_unguarded_program(self):
        with self.assertRaisesRegex(ValueError, "exact local"):
            patch_unlock_return(self.rom[:-1])
        with self.assertRaisesRegex(ValueError, "signature"):
            validate_crossing_machine_code(WRITEFLASH_UNSAFE_BCALL)

    def test_packaged_program_contains_original_machine_code(self):
        machine_code = fixture_machine_code()
        fixture = build_crossing_fixture(self.rom, machine_code)
        variable = decode_ti_variable_file(fixture.program)
        runner = decode_ti_variable_file(fixture.runner)
        body = variable.data[2:]
        recovered = bytes.fromhex(body[3:-1].decode("ascii"))

        self.assertEqual("EMUWF3E", variable.name)
        self.assertEqual("AWRUN3E", runner.name)
        self.assertEqual(b"\x0C\x00\xBB\x6A\x5FEMUWF3E\x11\x3F", runner.data)
        self.assertEqual(machine_code, recovered)
        self.assertNotEqual(fixture.source_rom_sha256, fixture.patched_rom_sha256)

    def test_builds_named_program_error_fixture(self):
        machine_code = error_fixture_machine_code()
        fixture = build_fixture(self.rom, machine_code, "program-error")
        variable = decode_ti_variable_file(fixture.program)
        runner = decode_ti_variable_file(fixture.runner)

        self.assertEqual("program-error", fixture.spec.name)
        self.assertEqual("EMUWFERR", variable.name)
        self.assertEqual("AWRUNERR", runner.name)
        self.assertEqual(
            b"\x0D\x00\xBB\x6A\x5FEMUWFERR\x11\x3F",
            runner.data,
        )
        self.assertEqual(
            {
                "entry-returns",
                "byte-entry-returns",
                "certificate-program-error",
                "locked-byte-noop",
                "low-source-cross",
                "erase-entry-returns",
                "certificate-erase-success",
                "erase-busy-range",
                "page-3e-cross",
                "program-error",
            },
            set(FLASH_FIXTURES),
        )

    def test_builds_guarded_certificate_program_error_fixture(self):
        fixture = build_fixture(
            self.rom,
            certificate_program_error_machine_code(),
            "certificate-program-error",
        )
        variable = decode_ti_variable_file(fixture.program)
        runner = decode_ti_variable_file(fixture.runner)

        self.assertEqual("EMUCFAIL", variable.name)
        self.assertEqual("ACFAIL", runner.name)
        self.assertTrue(fixture.spec.patch_unlock)
        self.assertNotEqual(fixture.source_rom_sha256, fixture.fixture_rom_sha256)

    def test_certificate_program_error_fixture_requires_direct_worker_call(self):
        machine_code = certificate_program_error_machine_code()

        with self.assertRaisesRegex(ValueError, "copied worker directly"):
            build_fixture(
                self.rom,
                machine_code + WRITEFLASH_UNSAFE_BCALL,
                "certificate-program-error",
            )

    def test_builds_unmodified_entry_returns_fixture(self):
        fixture = build_fixture(
            self.rom,
            entry_returns_machine_code(),
            "entry-returns",
        )
        variable = decode_ti_variable_file(fixture.program)
        runner = decode_ti_variable_file(fixture.runner)

        self.assertEqual("EMUWFENT", variable.name)
        self.assertEqual("AWRUNENT", runner.name)
        self.assertFalse(fixture.spec.patch_unlock)
        self.assertEqual(fixture.source_rom_sha256, fixture.patched_rom_sha256)
        self.assertEqual(self.rom, fixture.rom)

    def test_entry_returns_fixture_rejects_wrong_rom_and_unlock_output(self):
        machine_code = entry_returns_machine_code()
        with self.assertRaisesRegex(ValueError, "exact local"):
            build_fixture(self.rom[:-1], machine_code, "entry-returns")
        with self.assertRaisesRegex(ValueError, "must not write Flash unlock"):
            build_fixture(self.rom, machine_code + bytes.fromhex("d314"), "entry-returns")

    def test_builds_unmodified_byte_entry_returns_fixture(self):
        fixture = build_fixture(
            self.rom,
            byte_entry_returns_machine_code(),
            "byte-entry-returns",
        )
        variable = decode_ti_variable_file(fixture.program)
        runner = decode_ti_variable_file(fixture.runner)

        self.assertEqual("EMUWBENT", variable.name)
        self.assertEqual("AWBENTRY", runner.name)
        self.assertFalse(fixture.spec.patch_unlock)
        self.assertEqual(fixture.source_rom_sha256, fixture.fixture_rom_sha256)
        self.assertEqual(self.rom, fixture.rom)

    def test_byte_entry_fixture_rejects_unlock_output(self):
        machine_code = byte_entry_returns_machine_code() + bytes.fromhex("d314")

        with self.assertRaisesRegex(ValueError, "must not write Flash unlock"):
            build_fixture(self.rom, machine_code, "byte-entry-returns")

    def test_builds_guarded_locked_byte_noop_fixture(self):
        fixture = build_fixture(
            self.rom,
            locked_byte_noop_machine_code(),
            "locked-byte-noop",
        )
        variable = decode_ti_variable_file(fixture.program)
        runner = decode_ti_variable_file(fixture.runner)

        self.assertEqual("EMULOCK", variable.name)
        self.assertEqual("ALOCKED", runner.name)
        self.assertFalse(fixture.spec.patch_unlock)
        self.assertEqual(fixture.source_rom_sha256, fixture.fixture_rom_sha256)
        self.assertEqual(self.rom, fixture.rom)

    def test_locked_byte_fixture_rejects_direct_port14_output(self):
        machine_code = locked_byte_noop_machine_code() + bytes.fromhex("d314")

        with self.assertRaisesRegex(ValueError, "port 0x14"):
            build_fixture(self.rom, machine_code, "locked-byte-noop")

    def test_builds_guarded_low_source_cross_fixture(self):
        fixture = build_fixture(
            self.rom,
            low_source_cross_machine_code(),
            "low-source-cross",
        )
        variable = decode_ti_variable_file(fixture.program)
        runner = decode_ti_variable_file(fixture.runner)

        self.assertEqual("EMULOW", variable.name)
        self.assertEqual("ALOWSRC", runner.name)
        self.assertFalse(fixture.spec.patch_unlock)
        self.assertEqual(fixture.source_rom_sha256, fixture.fixture_rom_sha256)
        self.assertEqual(self.rom, fixture.rom)

    def test_low_source_fixture_requires_ram_restore(self):
        machine_code = low_source_cross_machine_code().replace(
            bytes.fromhex("320080"),
            b"",
            1,
        )

        with self.assertRaisesRegex(ValueError, "restore RAM"):
            build_fixture(self.rom, machine_code, "low-source-cross")

    def test_low_source_fixture_requires_ram_save_and_capture(self):
        machine_code = low_source_cross_machine_code().replace(
            bytes.fromhex("3a008032"),
            b"",
            1,
        )

        with self.assertRaisesRegex(ValueError, "save and capture RAM"):
            build_fixture(self.rom, machine_code, "low-source-cross")

    def test_builds_unmodified_erase_entry_returns_fixture(self):
        fixture = build_fixture(
            self.rom,
            erase_entry_returns_machine_code(),
            "erase-entry-returns",
        )
        variable = decode_ti_variable_file(fixture.program)
        runner = decode_ti_variable_file(fixture.runner)

        self.assertEqual("EMUERENT", variable.name)
        self.assertEqual("AERUNENT", runner.name)
        self.assertFalse(fixture.spec.patch_unlock)
        self.assertEqual(fixture.source_rom_sha256, fixture.fixture_rom_sha256)
        self.assertEqual(self.rom, fixture.rom)

    def test_erase_entry_fixture_rejects_wrong_rom_and_unlock_output(self):
        machine_code = erase_entry_returns_machine_code()
        with self.assertRaisesRegex(ValueError, "exact local"):
            build_fixture(self.rom[:-1], machine_code, "erase-entry-returns")
        with self.assertRaisesRegex(ValueError, "must not write Flash unlock"):
            build_fixture(
                self.rom,
                machine_code + bytes.fromhex("d314"),
                "erase-entry-returns",
            )

    def test_builds_guarded_certificate_erase_fixture(self):
        fixture = build_fixture(
            self.rom,
            certificate_erase_success_machine_code(),
            "certificate-erase-success",
        )
        variable = decode_ti_variable_file(fixture.program)
        runner = decode_ti_variable_file(fixture.runner)

        self.assertEqual("EMUCERAS", variable.name)
        self.assertEqual("ACERASE", runner.name)
        self.assertTrue(fixture.spec.patch_unlock)
        self.assertNotEqual(fixture.source_rom_sha256, fixture.fixture_rom_sha256)

    def test_builds_guarded_erase_busy_range_fixture(self):
        fixture = build_fixture(
            self.rom,
            erase_busy_range_machine_code(),
            "erase-busy-range",
        )
        variable = decode_ti_variable_file(fixture.program)
        runner = decode_ti_variable_file(fixture.runner)

        self.assertEqual("EMUERANG", variable.name)
        self.assertEqual("AERANGE", runner.name)
        self.assertTrue(fixture.spec.patch_unlock)

    def test_rejects_erase_busy_range_fixture_without_relock(self):
        machine_code = erase_busy_range_machine_code().replace(
            bytes.fromhex("3e3cd306cdd566"),
            b"",
            1,
        )

        with self.assertRaisesRegex(ValueError, "relock"):
            build_fixture(self.rom, machine_code, "erase-busy-range")

    def test_rejects_unknown_fixture(self):
        with self.assertRaisesRegex(ValueError, "unknown Flash fixture"):
            build_fixture(self.rom, error_fixture_machine_code(), "missing")


if __name__ == "__main__":
    unittest.main()
