"""Reusable build contracts for guarded Flash emulator fixtures.

Each fixture uses a copy of the exact local OS 2.55MP image and never edits the
source ROM. Fixtures that mutate Flash patch an unlock wrapper in that copy.
Every assembly program checks the ROM bytes it depends on before proceeding.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Callable

from ti84re.rom.signatures import TI84_PLUS_OS_255MP_SHA256
from ti84re.tifiles.program import asm_call_body, asmprgm_body, encode_program_file


ROM_SIZE = 0x100000
SOURCE_ROM_SHA256 = TI84_PLUS_OS_255MP_SHA256
UNLOCK_RETURN_OFFSET = 0xF3068
UNLOCK_RETURN_ORIGINAL = bytes.fromhex("f1cdb92bcdd566c9")
UNLOCK_RETURN_PATCHED = bytes.fromhex("f1c9000000000000")
WRITEFLASH_UNSAFE_BCALL = bytes.fromhex("ef8780")
WRITEFLASH_BCALL = bytes.fromhex("efc980")
WRITEABYTE_BCALL = bytes.fromhex("ef2180")
WRITEABYTE_SAFE_BCALL = bytes.fromhex("efc680")
ERASEFLASHPAGE_BCALL = bytes.fromhex("ef8480")
ERASECERTIFICATESECTOR_BCALL = bytes.fromhex("ef6080")
PATCH_SIGNATURE_CHECK = bytes.fromhex("216870")
ENTRY_SIGNATURE_CHECK = bytes.fromhex("21a64c")
PATCH_COMPARE_LOOP = bytes.fromhex("06081abe20")


@dataclass(frozen=True)
class FlashFixtureSpec:
    """Names, source, and probe-specific validation for one fixture."""

    name: str
    source_name: str
    program_name: str
    runner_name: str
    rom_name: str
    comment: str
    patch_unlock: bool
    warning: str
    validate_probe: Callable[[bytes], None]


@dataclass(frozen=True)
class FlashEmulatorFixture:
    """Generated emulator ROM and assembly-program artifacts."""

    spec: FlashFixtureSpec
    rom: bytes
    program: bytes
    runner: bytes
    machine_code_sha256: str
    source_rom_sha256: str
    fixture_rom_sha256: str

    @property
    def patched_rom_sha256(self) -> str:
        """Compatibility alias for callers of the original patch-only API."""

        return self.fixture_rom_sha256


def _validate_crossing_probe(machine_code: bytes) -> None:
    if PATCH_SIGNATURE_CHECK not in machine_code:
        raise ValueError("page-3E crossing fixture lacks the patched-ROM signature check")
    if PATCH_COMPARE_LOOP not in machine_code:
        raise ValueError("page-3E crossing fixture lacks its signature loop")
    if machine_code.count(WRITEFLASH_UNSAFE_BCALL) != 1:
        raise ValueError(
            "page-3E crossing fixture must contain one `_WriteFlashUnsafe` bcall"
        )
    if bytes.fromhex("3e3d11ff7f010200") not in machine_code:
        raise ValueError("page-3E crossing fixture lacks its boundary call inputs")
    if bytes.fromhex("40e0") not in machine_code:
        raise ValueError("page-3E crossing fixture lacks its two legal program bytes")


def _validate_program_error_probe(machine_code: bytes) -> None:
    if PATCH_SIGNATURE_CHECK not in machine_code:
        raise ValueError("program-error fixture lacks the patched-ROM signature check")
    if PATCH_COMPARE_LOOP not in machine_code:
        raise ValueError("program-error fixture lacks its signature loop")
    if machine_code.count(WRITEFLASH_UNSAFE_BCALL) != 1:
        raise ValueError(
            "program-error fixture must contain one `_WriteFlashUnsafe` bcall"
        )
    if bytes.fromhex("3e3d11ff7f010100") not in machine_code:
        raise ValueError("program-error fixture lacks its page-3D call inputs")
    if bytes.fromhex("d0") not in machine_code:
        raise ValueError("program-error fixture lacks its illegal program byte")
    if bytes.fromhex("f5e1") not in machine_code:
        raise ValueError("program-error fixture does not capture returned AF")
    if bytes.fromhex("3e3dd3063aff7f32") not in machine_code:
        raise ValueError("program-error fixture does not capture the stored byte")


def _validate_certificate_program_error_probe(machine_code: bytes) -> None:
    if PATCH_SIGNATURE_CHECK not in machine_code:
        raise ValueError(
            "certificate-program-error fixture lacks the patched-ROM signature check"
        )
    if bytes.fromhex("06081abec2") not in machine_code:
        raise ValueError(
            "certificate-program-error fixture lacks its patch-signature loop"
        )
    for sequence, label in (
        (bytes.fromhex("210a73"), "worker-head address"),
        (bytes.fromhex("060c1abec2"), "worker-head check"),
        (bytes.fromhex("217973"), "worker-tail address"),
        (bytes.fromhex("06121abec2"), "worker-tail check"),
        (bytes.fromhex("3e3ed3063a0040b7"), "target-byte guard"),
        (bytes.fromhex("3e3dd306210a73110081018100edb0"), "worker copy"),
        (bytes.fromhex("afd3063e3e110040010100"), "page-zero call inputs"),
        (bytes.fromhex("cd0081"), "worker call"),
        (bytes.fromhex("f5e1"), "AF capture"),
        (bytes.fromhex("db0632"), "restored-page capture"),
        (bytes.fromhex("3e3ed3063a004032"), "stored-byte capture"),
        (bytes.fromhex("3e3cd306cdd566"), "protected relock"),
    ):
        if sequence not in machine_code:
            raise ValueError(
                f"certificate-program-error fixture lacks its {label}"
            )
    if (
        WRITEFLASH_UNSAFE_BCALL in machine_code
        or WRITEABYTE_BCALL in machine_code
    ):
        raise ValueError(
            "certificate-program-error fixture must call the copied worker directly"
        )


def _validate_entry_returns_probe(machine_code: bytes) -> None:
    if ENTRY_SIGNATURE_CHECK not in machine_code:
        raise ValueError("entry-returns fixture lacks the worker-entry ROM check")
    if PATCH_COMPARE_LOOP not in machine_code:
        raise ValueError("entry-returns fixture lacks its signature loop")
    if bytes.fromhex("e3cb7ce3c0e63ffe") not in machine_code:
        raise ValueError("entry-returns fixture lacks the expected ROM signature")
    if machine_code.count(WRITEFLASH_BCALL) != 1:
        raise ValueError("entry-returns fixture must contain one `_WriteFlash` bcall")
    if machine_code.count(WRITEFLASH_UNSAFE_BCALL) != 2:
        raise ValueError(
            "entry-returns fixture must contain two `_WriteFlashUnsafe` bcalls"
        )
    if machine_code.count(bytes.fromhex("cda64c")) != 1:
        raise ValueError("entry-returns fixture must contain one guarded direct call")
    for inputs, label in (
        (bytes.fromhex("3e7e110040010100"), "safe page-3E"),
        (bytes.fromhex("3e7f110040010100"), "unsafe page-3F"),
        (bytes.fromhex("3e7d110040010000"), "zero-length"),
    ):
        if inputs not in machine_code:
            raise ValueError(f"entry-returns fixture lacks {label} inputs")
    if bytes.fromhex("d314") in machine_code:
        raise ValueError("entry-returns fixture must not write Flash unlock port 0x14")


def _validate_byte_entry_returns_probe(machine_code: bytes) -> None:
    if bytes.fromhex("219a4c") not in machine_code:
        raise ValueError("byte-entry fixture lacks its wrapper-entry ROM check")
    if bytes.fromhex("06101abec2") not in machine_code:
        raise ValueError("byte-entry fixture lacks its 16-byte signature loop")
    if bytes.fromhex("e63ffe3ec821788470010100e3cb7ce3") not in machine_code:
        raise ValueError("byte-entry fixture lacks the expected wrapper bytes")
    if machine_code.count(WRITEABYTE_SAFE_BCALL) != 2:
        raise ValueError("byte-entry fixture must contain two `_WriteAByteSafe` bcalls")
    if machine_code.count(WRITEABYTE_BCALL) != 1:
        raise ValueError("byte-entry fixture must contain one `_WriteAByte` bcall")
    if machine_code.count(bytes.fromhex("cd9f4c")) != 1:
        raise ValueError("byte-entry fixture must contain one guarded direct call")
    for inputs, label in (
        (bytes.fromhex("3e7e013322115544217766"), "safe page-3E"),
        (bytes.fromhex("3e7f015544117766219988"), "safe page-3F"),
        (bytes.fromhex("3e7f01665511887721aa99"), "unsafe page-3F"),
        (bytes.fromhex("373ea501776611998821bbaa"), "direct-call"),
    ):
        if inputs not in machine_code:
            raise ValueError(f"byte-entry fixture lacks {label} inputs")
    if machine_code.count(bytes.fromhex("3a788432")) != 5:
        raise ValueError("byte-entry fixture must save and capture OP1 five times")
    if machine_code.count(bytes.fromhex("327884")) != 2:
        raise ValueError("byte-entry fixture must seed and restore OP1")
    if bytes.fromhex("d314") in machine_code:
        raise ValueError("byte-entry fixture must not write Flash unlock port 0x14")


def _validate_locked_byte_noop_probe(machine_code: bytes) -> None:
    for check, label in (
        (bytes.fromhex("219a4c"), "byte-wrapper"),
        (bytes.fromhex("21d566"), "protected-lock"),
    ):
        if check not in machine_code:
            raise ValueError(f"locked-byte fixture lacks its {label} ROM check")
    if bytes.fromhex("06101abec0") not in machine_code:
        raise ValueError("locked-byte fixture lacks its signature loop")
    for signature, label in (
        (bytes.fromhex("e63ffe3ec821788470010100e3cb7ce3"), "byte wrapper"),
        (bytes.fromhex("00000000f5af00f30000ed56f3d314f3"), "lock wrapper"),
    ):
        if signature not in machine_code:
            raise ValueError(f"locked-byte fixture lacks the expected {label} bytes")
    if machine_code.count(WRITEABYTE_BCALL) != 1:
        raise ValueError("locked-byte fixture must contain one `_WriteAByte` bcall")
    if WRITEABYTE_SAFE_BCALL in machine_code:
        raise ValueError("locked-byte fixture must not call `_WriteAByteSafe`")
    if machine_code.count(bytes.fromhex("cdd566")) != 1:
        raise ValueError("locked-byte fixture must call the protected lock wrapper once")
    if machine_code.count(bytes.fromhex("d314")) != 1:
        raise ValueError("locked-byte fixture may contain port 0x14 only in its signature")
    if bytes.fromhex("3e3dd3063aff7ffe50") not in machine_code:
        raise ValueError("locked-byte fixture lacks its source-byte guard")
    if bytes.fromhex("cdd566db02") not in machine_code:
        raise ValueError("locked-byte fixture does not read status after locking")
    if bytes.fromhex("e604c2") not in machine_code:
        raise ValueError("locked-byte fixture does not abort when Flash is unlocked")
    if bytes.fromhex("3e3d11ff7f06400e99") not in machine_code:
        raise ValueError("locked-byte fixture lacks its legal program inputs")
    if bytes.fromhex("3e3dd3063aff7f32") not in machine_code:
        raise ValueError("locked-byte fixture does not capture the final array byte")
    if machine_code.count(bytes.fromhex("3a788432")) != 2:
        raise ValueError("locked-byte fixture must save and capture OP1")
    if machine_code.count(bytes.fromhex("327884")) != 1:
        raise ValueError("locked-byte fixture must restore OP1 once")


def _validate_low_source_cross_probe(machine_code: bytes) -> None:
    for check, label in (
        (bytes.fromhex("216800"), "fixed-page source"),
        (bytes.fromhex("21ca4c"), "block-worker head"),
        (bytes.fromhex("21d566"), "protected-lock wrapper"),
    ):
        if check not in machine_code:
            raise ValueError(f"low-source fixture lacks its {label} ROM check")
    for signature, label in (
        (bytes.fromhex("4d50"), "fixed-page source"),
        (bytes.fromhex("e63fd306cb7c2004fdcb25cefdcb254e"), "worker head"),
        (bytes.fromhex("00000000f5af00f30000ed56f3d314f3"), "lock wrapper"),
    ):
        if signature not in machine_code:
            raise ValueError(
                f"low-source fixture lacks the expected {label} bytes"
            )
    if machine_code.count(WRITEFLASH_UNSAFE_BCALL) != 1:
        raise ValueError(
            "low-source fixture must contain one `_WriteFlashUnsafe` bcall"
        )
    if bytes.fromhex("3e3d11ff7f010200216800ef8780") not in machine_code:
        raise ValueError("low-source fixture lacks its crossing call inputs")
    if bytes.fromhex("cb8e") not in machine_code:
        raise ValueError("low-source fixture does not clear the source-mode flag")
    if machine_code.count(bytes.fromhex("3a008032")) != 2:
        raise ValueError("low-source fixture must save and capture RAM 0x8000")
    if machine_code.count(bytes.fromhex("320080")) != 1:
        raise ValueError("low-source fixture does not restore RAM 0x8000")
    if machine_code.count(bytes.fromhex("cdd566")) != 1:
        raise ValueError("low-source fixture must call the lock wrapper once")
    if machine_code.count(bytes.fromhex("d314")) != 1:
        raise ValueError("low-source fixture may contain port 0x14 only in its signature")


def _validate_erase_entry_returns_probe(machine_code: bytes) -> None:
    if bytes.fromhex("06081abec0") not in machine_code:
        raise ValueError("erase-entry fixture lacks its signature-check loop")
    for check, label in (
        (bytes.fromhex("211e4c"), "`_EraseFlashPage`"),
        (bytes.fromhex("212a4c"), "`_EraseFlash`"),
        (bytes.fromhex("213f4e"), "`_EraseCertificateSector`"),
    ):
        if check not in machine_code:
            raise ValueError(f"erase-entry fixture lacks the {label} ROM check")
    for signature, label in (
        (bytes.fromhex("210040e63ffe3ec8"), "page entry"),
        (bytes.fromhex("e3cb7ce3c0dde5dd"), "erase entry"),
        (bytes.fromhex("f57cee40fe002809"), "certificate entry"),
    ):
        if signature not in machine_code:
            raise ValueError(f"erase-entry fixture lacks the expected {label} bytes")
    if machine_code.count(ERASEFLASHPAGE_BCALL) != 1:
        raise ValueError("erase-entry fixture must contain one `_EraseFlashPage` bcall")
    if machine_code.count(ERASECERTIFICATESECTOR_BCALL) != 1:
        raise ValueError(
            "erase-entry fixture must contain one `_EraseCertificateSector` bcall"
        )
    if machine_code.count(bytes.fromhex("cd2a4c")) != 1:
        raise ValueError("erase-entry fixture must contain one guarded direct call")
    if bytes.fromhex("d314") in machine_code:
        raise ValueError("erase-entry fixture must not write Flash unlock port 0x14")


def _validate_certificate_erase_success_probe(machine_code: bytes) -> None:
    if PATCH_SIGNATURE_CHECK not in machine_code:
        raise ValueError(
            "certificate-erase fixture lacks the patched-ROM signature check"
        )
    if PATCH_COMPARE_LOOP not in machine_code:
        raise ValueError("certificate-erase fixture lacks its signature loop")
    if machine_code.count(ERASECERTIFICATESECTOR_BCALL) != 1:
        raise ValueError(
            "certificate-erase fixture must contain one "
            "`_EraseCertificateSector` bcall"
        )
    if bytes.fromhex("af373ea5210040") not in machine_code:
        raise ValueError("certificate-erase fixture lacks its seeded AF and target")
    if bytes.fromhex("f5e1") not in machine_code:
        raise ValueError("certificate-erase fixture does not capture returned AF")
    if bytes.fromhex("3e3ed3063a004032") not in machine_code:
        raise ValueError("certificate-erase fixture does not capture the erased byte")


def _validate_erase_busy_range_probe(machine_code: bytes) -> None:
    if PATCH_SIGNATURE_CHECK not in machine_code:
        raise ValueError("erase-range fixture lacks the patched-ROM signature check")
    if PATCH_COMPARE_LOOP not in machine_code:
        raise ValueError("erase-range fixture lacks its signature loop")
    if bytes.fromhex("cd5870") not in machine_code:
        raise ValueError("erase-range fixture does not call the guarded unlock wrapper")
    for sequence, expected_count, label in (
        (bytes.fromhex("3e02d3063eaa32aa6a"), 2, "unlock-address AA writes"),
        (bytes.fromhex("3e01d3063e55325555"), 2, "unlock-address 55 writes"),
        (bytes.fromhex("3e02d3063e8032aa6a"), 1, "erase setup write"),
        (bytes.fromhex("3e3ed3063e30320040"), 1, "sector erase target"),
    ):
        if machine_code.count(sequence) != expected_count:
            raise ValueError(
                f"erase-range fixture must contain {expected_count} {label}"
            )
    for loop, label in (
        (bytes.fromhex("3a0040cb5f28"), "DQ3 active-erase loop"),
        (bytes.fromhex("3a0040cb7f28"), "DQ7 completion loop"),
    ):
        if loop not in machine_code:
            raise ValueError(f"erase-range fixture lacks its {label}")
    for sequence, expected_count, label in (
        (bytes.fromhex("3aff5f"), 2, "selected-sector end reads"),
        (bytes.fromhex("3a0060"), 2, "adjacent-sector start reads"),
        (bytes.fromhex("3e3dd3063aff7f"), 2, "preceding-sector reads"),
        (bytes.fromhex("3e3fd3063a0040"), 2, "boot-sector reads"),
        (bytes.fromhex("3e08d3063a0040"), 2, "distant-sector reads"),
    ):
        if machine_code.count(sequence) != expected_count:
            raise ValueError(
                f"erase-range fixture must contain {expected_count} {label}"
            )
    if bytes.fromhex("3e3cd306cdd566") not in machine_code:
        raise ValueError("erase-range fixture does not relock Flash")
    if (
        ERASECERTIFICATESECTOR_BCALL in machine_code
        or ERASEFLASHPAGE_BCALL in machine_code
    ):
        raise ValueError("erase-range fixture must issue its raw command directly")


FLASH_FIXTURES = {
    spec.name: spec
    for spec in (
        FlashFixtureSpec(
            name="page-3e-cross",
            source_name="writeflash-3e-cross.asm",
            program_name="EMUWF3E",
            runner_name="AWRUN3E",
            rom_name="ti84plus-writeflash-3e-patched.rom",
            comment="Emulator-only WriteFlash crossing fixture",
            patch_unlock=True,
            warning=(
                "emulator-only; the program exits unless the patched-ROM "
                "signature is present"
            ),
            validate_probe=_validate_crossing_probe,
        ),
        FlashFixtureSpec(
            name="program-error",
            source_name="writeflash-program-error.asm",
            program_name="EMUWFERR",
            runner_name="AWRUNERR",
            rom_name="ti84plus-writeflash-error-patched.rom",
            comment="Emulator-only WriteFlash program-error fixture",
            patch_unlock=True,
            warning=(
                "emulator-only; the program exits unless the patched-ROM "
                "signature is present"
            ),
            validate_probe=_validate_program_error_probe,
        ),
        FlashFixtureSpec(
            name="certificate-program-error",
            source_name="certificate-program-error.asm",
            program_name="EMUCFAIL",
            runner_name="ACFAIL",
            rom_name="ti84plus-certificate-program-error-patched.rom",
            comment="Emulator-only certificate-program error fixture",
            patch_unlock=True,
            warning=(
                "emulator-only; directly runs the guarded page-3D worker in a "
                "patched ROM copy"
            ),
            validate_probe=_validate_certificate_program_error_probe,
        ),
        FlashFixtureSpec(
            name="entry-returns",
            source_name="writeflash-entry-returns.asm",
            program_name="EMUWFENT",
            runner_name="AWRUNENT",
            rom_name="ti84plus-writeflash-entry.rom",
            comment="Read-only WriteFlash entry-return fixture",
            patch_unlock=False,
            warning=(
                "read-only; the program verifies the worker-entry bytes and "
                "never unlocks Flash"
            ),
            validate_probe=_validate_entry_returns_probe,
        ),
        FlashFixtureSpec(
            name="byte-entry-returns",
            source_name="writeabyte-entry-returns.asm",
            program_name="EMUWBENT",
            runner_name="AWBENTRY",
            rom_name="ti84plus-writeabyte-entry.rom",
            comment="Read-only WriteAByte entry-return fixture",
            patch_unlock=False,
            warning=(
                "read-only; the program verifies the byte-wrapper bytes and "
                "never unlocks Flash"
            ),
            validate_probe=_validate_byte_entry_returns_probe,
        ),
        FlashFixtureSpec(
            name="locked-byte-noop",
            source_name="writeabyte-locked-noop.asm",
            program_name="EMULOCK",
            runner_name="ALOCKED",
            rom_name="ti84plus-writeabyte-locked.rom",
            comment="Locked-Flash WriteAByte no-op fixture",
            patch_unlock=False,
            warning=(
                "emulator-only read-only trace; forces the ASIC Flash lock and "
                "aborts unless port 0x02 confirms it"
            ),
            validate_probe=_validate_locked_byte_noop_probe,
        ),
        FlashFixtureSpec(
            name="low-source-cross",
            source_name="writeflash-low-source-cross.asm",
            program_name="EMULOW",
            runner_name="ALOWSRC",
            rom_name="ti84plus-writeflash-low-source.rom",
            comment="Locked-Flash low-source crossing fixture",
            patch_unlock=False,
            warning=(
                "emulator-only; temporarily writes and restores RAM 0x8000 "
                "while the guarded probe keeps Flash locked"
            ),
            validate_probe=_validate_low_source_cross_probe,
        ),
        FlashFixtureSpec(
            name="erase-entry-returns",
            source_name="eraseflash-entry-returns.asm",
            program_name="EMUERENT",
            runner_name="AERUNENT",
            rom_name="ti84plus-eraseflash-entry.rom",
            comment="Read-only erase-entry return fixture",
            patch_unlock=False,
            warning=(
                "read-only; the program verifies all erase-entry bytes and "
                "never unlocks Flash"
            ),
            validate_probe=_validate_erase_entry_returns_probe,
        ),
        FlashFixtureSpec(
            name="certificate-erase-success",
            source_name="eraseflash-certificate-success.asm",
            program_name="EMUCERAS",
            runner_name="ACERASE",
            rom_name="ti84plus-certificate-erase-patched.rom",
            comment="Emulator-only certificate erase success fixture",
            patch_unlock=True,
            warning=(
                "emulator-only; erases the first certificate half in a guarded "
                "patched ROM copy"
            ),
            validate_probe=_validate_certificate_erase_success_probe,
        ),
        FlashFixtureSpec(
            name="erase-busy-range",
            source_name="eraseflash-busy-range.asm",
            program_name="EMUERANG",
            runner_name="AERANGE",
            rom_name="ti84plus-eraseflash-range-patched.rom",
            comment="Emulator-only erase-busy range fixture",
            patch_unlock=True,
            warning=(
                "emulator-only; samples cross-sector reads during an erase in "
                "a guarded patched ROM copy"
            ),
            validate_probe=_validate_erase_busy_range_probe,
        ),
    )
}

# Compatibility names for callers of the original crossing-only API.
PROGRAM_NAME = FLASH_FIXTURES["page-3e-cross"].program_name
RUNNER_NAME = FLASH_FIXTURES["page-3e-cross"].runner_name


def patch_unlock_return(rom: bytes) -> bytes:
    """Patch the known page-3C unlock wrapper to return while still unlocked."""

    validate_source_rom(rom)
    end = UNLOCK_RETURN_OFFSET + len(UNLOCK_RETURN_ORIGINAL)
    if rom[UNLOCK_RETURN_OFFSET:end] != UNLOCK_RETURN_ORIGINAL:
        raise ValueError("unlock-wrapper bytes do not match the audited ROM")
    patched = bytearray(rom)
    patched[UNLOCK_RETURN_OFFSET:end] = UNLOCK_RETURN_PATCHED
    return bytes(patched)


def validate_source_rom(rom: bytes) -> None:
    """Require the exact ROM image audited by every fixture."""

    digest = hashlib.sha256(rom).hexdigest()
    if len(rom) != ROM_SIZE or digest != SOURCE_ROM_SHA256:
        raise ValueError(
            "fixture requires the exact local TI-84 Plus OS 2.55MP ROM "
            f"({SOURCE_ROM_SHA256})"
        )


def validate_machine_code(spec: FlashFixtureSpec, machine_code: bytes) -> None:
    """Require the common guard plus the selected probe's call contract."""

    if not machine_code:
        raise ValueError(f"{spec.name} fixture machine code is empty")
    spec.validate_probe(machine_code)


def validate_crossing_machine_code(machine_code: bytes) -> None:
    """Validate machine code for the original page-3E crossing fixture."""

    validate_machine_code(FLASH_FIXTURES["page-3e-cross"], machine_code)


def build_fixture(
    rom: bytes,
    machine_code: bytes,
    fixture_name: str,
) -> FlashEmulatorFixture:
    """Return ROM-copy and link-file bytes for one named fixture."""

    try:
        spec = FLASH_FIXTURES[fixture_name]
    except KeyError as error:
        choices = ", ".join(sorted(FLASH_FIXTURES))
        raise ValueError(
            f"unknown Flash fixture {fixture_name!r}; choose {choices}"
        ) from error
    validate_machine_code(spec, machine_code)
    if spec.patch_unlock:
        fixture_rom = patch_unlock_return(rom)
    else:
        validate_source_rom(rom)
        fixture_rom = rom
    program = encode_program_file(
        spec.program_name,
        asmprgm_body(machine_code),
        comment=spec.comment,
    )
    runner = encode_program_file(
        spec.runner_name,
        asm_call_body(spec.program_name),
        comment=f"Run {spec.comment.lower()}",
    )
    return FlashEmulatorFixture(
        spec=spec,
        rom=fixture_rom,
        program=program,
        runner=runner,
        machine_code_sha256=hashlib.sha256(machine_code).hexdigest(),
        source_rom_sha256=hashlib.sha256(rom).hexdigest(),
        fixture_rom_sha256=hashlib.sha256(fixture_rom).hexdigest(),
    )


def build_crossing_fixture(rom: bytes, machine_code: bytes) -> FlashEmulatorFixture:
    """Return validated patched-ROM and link-file bytes for the crossing run."""

    return build_fixture(rom, machine_code, "page-3e-cross")
