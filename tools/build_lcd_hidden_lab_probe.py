#!/usr/bin/env python3
"""Build the separately gated hidden-column LCD laboratory probe."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

from build_hardware_probes import (
    CREATE_APPVAR_COPY,
    DISPLAY_BCALL_COUNTS,
    DISPLAY_COMPACT_SIGNATURE,
    DISPLAY_CRC_SIGNATURE,
    DISPLAY_DONE_SIGNATURE,
    DISPLAY_IFF_GUARD,
    PROBE_DIR,
    PROBE_START,
    PROGRAM_LIMIT,
    USER_MEM,
)
from hardware_probe import APPVAR_TYPE, PROBE_FORMAT_VERSION, PROBE_MAGIC
from ti_program import asmprgm_body, encode_program_file


SOURCE = PROBE_DIR / "lcd-hidden-lab.asm"
PROGRAM = "HWPLAB"
APPVAR = "HWPLAB01"
PROBE_ID = 17
PAYLOAD_SIZE = 2335
ACK_TEXT = "I_UNDERSTAND_HIDDEN_LCD_WRITES_CAN_REQUIRE_A_RESET"
ACK_VALUE = 0x4C43


class LcdHiddenLabBuildError(ValueError):
    """A required laboratory recovery gate or artifact invariant failed."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_byte(value: str) -> int:
    """Parse one decimal or ``0x``-prefixed byte."""

    try:
        result = int(value, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected an integer byte") from error
    if not 0 <= result <= 0xFF:
        raise argparse.ArgumentTypeError("ASIC identity must fit in one byte")
    return result


def validate_recovery_inputs(
    *, acknowledgement: str, expected_asic: int, controller_id: str,
    backup_file: Path, expected_backup_sha256: str, recovery_notes: Path,
) -> dict[str, object]:
    """Validate and describe the operator-supplied recovery gates."""

    if acknowledgement != ACK_TEXT:
        raise LcdHiddenLabBuildError(
            f"--acknowledgement must equal {ACK_TEXT!r}"
        )
    if not 0 <= expected_asic <= 0xFF:
        raise LcdHiddenLabBuildError("--expected-asic must fit in one byte")
    normalized = controller_id.strip()
    if len(normalized) < 3 or normalized.lower() in {"unknown", "unspecified", "n/a"}:
        raise LcdHiddenLabBuildError(
            "--controller-id must identify the inspected LCD module or test unit"
        )
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_backup_sha256):
        raise LcdHiddenLabBuildError(
            "--expected-backup-sha256 must contain 64 hexadecimal digits"
        )
    if int(expected_backup_sha256, 16) == 0:
        raise LcdHiddenLabBuildError(
            "--expected-backup-sha256 must identify a completed backup"
        )
    if not backup_file.is_file():
        raise LcdHiddenLabBuildError("--backup-file must name an existing file")
    backup = backup_file.read_bytes()
    if not backup:
        raise LcdHiddenLabBuildError("--backup-file must not be empty")
    backup_digest = sha256(backup)
    if backup_digest != expected_backup_sha256.lower():
        raise LcdHiddenLabBuildError("backup file SHA-256 does not match the expected hash")
    if not recovery_notes.is_file():
        raise LcdHiddenLabBuildError("--recovery-notes must name an existing file")
    notes = recovery_notes.read_bytes()
    normalized_notes = notes.decode("utf-8", errors="ignore").lower()
    required_terms = {"backup", "reset", "restore"}
    missing_terms = sorted(term for term in required_terms if term not in normalized_notes)
    if len(notes.strip()) < 40 or missing_terms:
        raise LcdHiddenLabBuildError(
            "--recovery-notes must contain specific backup, reset, and restore steps"
        )
    return {
        "acknowledgement": acknowledgement,
        "expected_asic": expected_asic,
        "controller_id": normalized,
        "backup": {
            "name": backup_file.name,
            "size": len(backup),
            "sha256": backup_digest,
        },
        "recovery_notes": {
            "name": recovery_notes.name,
            "size": len(notes),
            "sha256": sha256(notes),
        },
    }


def validate_machine_code(machine_code: bytes, *, expected_asic: int) -> None:
    """Require the guarded entry, pending result, restore frame, and display."""

    if machine_code[:3] != bytes((0xC3, PROBE_START & 0xFF, PROBE_START >> 8)):
        raise LcdHiddenLabBuildError("laboratory probe has an unexpected entry jump")
    if USER_MEM + len(machine_code) > PROGRAM_LIMIT:
        raise LcdHiddenLabBuildError("laboratory probe extends beyond user RAM")
    if CREATE_APPVAR_COPY not in machine_code:
        raise LcdHiddenLabBuildError("laboratory probe omits pending AppVar creation")
    marker = bytes((APPVAR_TYPE,)) + APPVAR.encode("ascii")
    if machine_code.count(marker) != 1:
        raise LcdHiddenLabBuildError("laboratory result AppVar marker differs")
    frame_size = 10 + PAYLOAD_SIZE
    frame = machine_code[-frame_size:]
    expected_prefix = (
        PROBE_MAGIC
        + bytes((PROBE_FORMAT_VERSION, PROBE_ID))
        + PAYLOAD_SIZE.to_bytes(2, "little")
    )
    if not frame.startswith(expected_prefix) or any(frame[8:]):
        raise LcdHiddenLabBuildError("laboratory result frame layout differs")
    if machine_code.count(b"HWPLAB CODE \0") != 1:
        raise LcdHiddenLabBuildError("laboratory verification label differs")
    if machine_code.count(DISPLAY_IFF_GUARD) != 1:
        raise LcdHiddenLabBuildError("laboratory display lacks the entry-IFF guard")
    if machine_code.count(DISPLAY_CRC_SIGNATURE) != 1:
        raise LcdHiddenLabBuildError("laboratory frame CRC loop differs")
    for bcall, count in DISPLAY_BCALL_COUNTS.items():
        if machine_code.count(bcall) != count:
            raise LcdHiddenLabBuildError("laboratory display bcall inventory differs")
    if machine_code.count(DISPLAY_COMPACT_SIGNATURE) != 1:
        raise LcdHiddenLabBuildError("laboratory compact-code alphabet differs")
    if machine_code.count(DISPLAY_DONE_SIGNATURE) != 1:
        raise LcdHiddenLabBuildError("laboratory compact-display marker differs")
    if ACK_VALUE.to_bytes(2, "little") not in machine_code:
        raise LcdHiddenLabBuildError("laboratory acknowledgement constant is absent")
    if bytes((0xFE, expected_asic)) not in machine_code:
        raise LcdHiddenLabBuildError("laboratory ASIC comparison is absent")
    if bytes.fromhex("3EC0D30031F7FFCD") not in machine_code:
        raise LcdHiddenLabBuildError("OS 2.55MP fixed-page signature is absent")
    create_call = bytes((0xCD, (USER_MEM + 3) & 0xFF, (USER_MEM + 3) >> 8))
    if machine_code.count(create_call) != 1:
        raise LcdHiddenLabBuildError("pending AppVar creation call differs")
    first_lcd_write = min(machine_code.index(b"\xD3\x10"), machine_code.index(b"\xD3\x11"))
    if machine_code.index(create_call) > first_lcd_write:
        raise LcdHiddenLabBuildError("LCD mutation can occur before pending result creation")
    if (
        machine_code.count(bytes.fromhex("010003")) != 1
        or machine_code.count(bytes.fromhex("060C")) < 4
        or machine_code.count(bytes.fromhex("0E40")) < 4
    ):
        raise LcdHiddenLabBuildError("full 12-by-64 visible bounds are absent")


def assemble(*, spasm: str, expected_asic: int) -> bytes:
    """Assemble and validate the exact laboratory image."""

    with tempfile.TemporaryDirectory(prefix="ti84-lcd-hidden-lab-") as directory:
        raw_path = Path(directory) / "HWPLAB.bin"
        completed = subprocess.run(
            [
                spasm,
                "-N",
                "-I",
                str(PROBE_DIR),
                f"-DLCD_HIDDEN_LAB_ACK=${ACK_VALUE:04X}",
                f"-DEXPECTED_ASIC=${expected_asic:02X}",
                str(SOURCE),
                str(raw_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode:
            detail = (completed.stderr or completed.stdout).strip()
            raise RuntimeError(f"SPASM failed for the hidden LCD laboratory probe: {detail}")
        machine_code = raw_path.read_bytes()
    validate_machine_code(machine_code, expected_asic=expected_asic)
    return machine_code


def build(
    output_dir: Path, *, spasm: str, expected_asic: int, recovery: dict[str, object]
) -> dict[str, object]:
    """Build one transfer file and its recovery-bound manifest."""

    if output_dir.exists():
        raise LcdHiddenLabBuildError(f"refusing to reuse existing output directory {output_dir}")
    machine_code = assemble(spasm=spasm, expected_asic=expected_asic)
    program = encode_program_file(
        PROGRAM,
        asmprgm_body(machine_code),
        comment="Recovery-gated hidden LCD lab probe",
    )
    manifest = {
        "format": 1,
        "laboratory_only": True,
        "program": PROGRAM,
        "result_appvar": APPVAR,
        "probe_id": PROBE_ID,
        "payload_size": PAYLOAD_SIZE,
        "source": "tools/hardware-probes/lcd-hidden-lab.asm",
        "machine_code_size": len(machine_code),
        "machine_code_sha256": sha256(machine_code),
        "program_file_size": len(program),
        "program_file_sha256": sha256(program),
        "recovery": recovery,
    }
    output_dir.mkdir(parents=True)
    (output_dir / f"{PROGRAM}.8xp").write_bytes(program)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--spasm", default="spasm")
    parser.add_argument("--acknowledgement", required=True)
    parser.add_argument("--expected-asic", required=True, type=parse_byte)
    parser.add_argument("--controller-id", required=True)
    parser.add_argument("--backup-file", required=True, type=Path)
    parser.add_argument("--expected-backup-sha256", required=True)
    parser.add_argument("--recovery-notes", required=True, type=Path)
    args = parser.parse_args()
    try:
        recovery = validate_recovery_inputs(
            acknowledgement=args.acknowledgement,
            expected_asic=args.expected_asic,
            controller_id=args.controller_id,
            backup_file=args.backup_file,
            expected_backup_sha256=args.expected_backup_sha256,
            recovery_notes=args.recovery_notes,
        )
        manifest = build(
            args.output_dir,
            spasm=args.spasm,
            expected_asic=args.expected_asic,
            recovery=recovery,
        )
    except (LcdHiddenLabBuildError, OSError, RuntimeError) as error:
        parser.error(str(error))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
