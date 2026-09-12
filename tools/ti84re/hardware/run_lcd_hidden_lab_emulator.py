#!/usr/bin/env python3
"""Run the exact hidden-column LCD laboratory image in a pinned emulator core."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import tempfile
from pathlib import Path

from ti84re.hardware.build_lcd_hidden_lab_probe import PAYLOAD_SIZE, PROBE_ID, PROGRAM, assemble
from ti84re.hardware.probe import (
    decode_probe_frame,
    decode_probe_measurements,
    probe_verification_code,
)
from ti84re.emulators.probe_cli import (
    DEFAULT_ROM,
    emit_result,
    require_exact_hash,
    require_fresh_output_dir,
    require_output_absent,
    write_json,
)
from ti84re.rom.signatures import TI84_PLUS_OS_255MP_SHA256
from ti84re.hardware.run_exact_probe import parse_exact_output
from ti84re.emulators.tilem.core import TILEM_COMMIT
from ti84re.emulators.wabbitemu.headless import WABBITEMU_COMMIT


def validate_capture(fields: dict[str, str], *, backend: str, image_size: int):
    """Validate exact execution, resident-frame synchronization, and display CRC."""

    expected_mode = {"tilem": "tilem-exact-probe", "wabbitemu": "exact-probe"}[
        backend
    ]
    if fields["mode"] != expected_mode or fields["completed"] != "1":
        raise ValueError("exact runner did not complete the selected backend")
    if int(fields["probe_id"], 0) != PROBE_ID:
        raise ValueError("exact runner returned the wrong probe ID")
    if int(fields["payload_size"], 0) != PAYLOAD_SIZE:
        raise ValueError("exact runner returned the wrong payload size")
    if int(fields["probe_size"], 0) != image_size:
        raise ValueError("exact runner executed a different machine image")
    staging = bytes.fromhex(fields["frame_hex"])
    resident = bytes.fromhex(fields["appvar_frame_hex"])
    if fields["appvar_matches"] != "1" or staging != resident:
        raise ValueError("resident AppVar frame does not match the restored staging frame")
    frame = decode_probe_frame(staging)
    code = probe_verification_code(frame)
    if int(fields["display_code"], 0) != code:
        raise ValueError("displayed decimal code does not match the frame CRC")
    measurements = decode_probe_measurements(frame)
    if measurements["outcome"] != "completed":
        raise ValueError(f"laboratory probe reported {measurements['outcome']}")
    if not measurements["restoration"]["matches"]:
        raise ValueError("laboratory probe did not verify restoration")
    return frame, measurements, code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("tilem", "wabbitemu"), required=True)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-binary-sha256", required=True)
    parser.add_argument("--expected-asic", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--spasm", default="spasm")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        require_output_absent(args.output_dir)
        rom_sha256 = require_exact_hash(
            args.rom, TI84_PLUS_OS_255MP_SHA256, "OS 2.55MP ROM"
        )
        binary_sha256 = require_exact_hash(
            args.binary, args.expected_binary_sha256, "exact runner"
        )
        if not 0 <= args.expected_asic <= 0xFF:
            raise ValueError("--expected-asic must fit in one byte")
        image = assemble(spasm=args.spasm, expected_asic=args.expected_asic)
        with tempfile.TemporaryDirectory(prefix="ti84-lcd-hidden-emulator-") as directory:
            image_path = Path(directory) / f"{PROGRAM}.bin"
            image_path.write_bytes(image)
            command = [
                str(args.binary),
                "--exact-probe",
                str(args.rom),
                str(image_path),
                str(PROBE_ID),
                str(PAYLOAD_SIZE),
            ]
            if args.backend == "tilem":
                command.append("300000000")
            else:
                command.extend(("5000000", "200000000"))
            completed = subprocess.run(
                command, text=True, capture_output=True, check=False
            )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise ValueError(f"exact runner failed: {detail}")
        fields = parse_exact_output(completed.stdout)
        frame, measurements, code = validate_capture(
            fields, backend=args.backend, image_size=len(image)
        )
        emulator = "TilEm" if args.backend == "tilem" else "Wabbitemu"
        commit = TILEM_COMMIT if args.backend == "tilem" else WABBITEMU_COMMIT
        result = {
            "schema": "ti84p-re.lcd-hidden-lab-emulator.v1",
            "emulator": emulator,
            "commit": commit,
            "backend": args.backend,
            "binary": str(args.binary),
            "binary_sha256": binary_sha256,
            "source_rom": str(args.rom),
            "source_rom_sha256": rom_sha256,
            "expected_asic": args.expected_asic,
            "program": PROGRAM,
            "machine_code_size": len(image),
            "machine_code_sha256": hashlib.sha256(image).hexdigest(),
            "native_fields": fields,
            "decoded_frame": {
                "probe_id": frame.probe_id,
                "asic_id": frame.asic_id,
                "status": frame.status,
                "verification_code_decimal": code,
                "measurements": measurements,
            },
            "launch": "exact user-RAM injection after a guarded retail-ROM baseline",
            "host_intercepts": (
                "_CreateAppVar is redirected to private emulator RAM; execution "
                "stops at the first display bcall after the assembly CRC routine"
            ),
            "evidence_scope": (
                "exact assembly measurement and restoration in an emulator LCD "
                "model; not physical-controller safety or geometry evidence"
            ),
        }
        require_fresh_output_dir(args.output_dir)
        (args.output_dir / f"{PROGRAM}.bin").write_bytes(image)
        manifest = write_json(args.output_dir / "manifest.json", result)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    emit_result(
        result,
        manifest,
        as_json=args.json,
        summary=(
            f"{emulator} hidden LCD lab: {measurements}",
            f"verification code: {code}",
        ),
    )


if __name__ == "__main__":
    main()
