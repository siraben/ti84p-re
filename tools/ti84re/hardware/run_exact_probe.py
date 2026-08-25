#!/usr/bin/env python3
"""Run one displayed hardware probe unchanged in a pinned emulator core."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import tempfile
from pathlib import Path

from ti84re.hardware.build_probes import PROBES, assemble_machine_code
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
from ti84re.emulators.tilem.core import TILEM_COMMIT
from ti84re.emulators.wabbitemu.headless import WABBITEMU_COMMIT


DISPLAYED_PROBES = tuple(PROBES)
FIELD_PATTERN = re.compile(r"(?P<key>[a-z0-9_]+)=(?P<value>\S+)")


def parse_exact_output(output: str) -> dict[str, str]:
    """Parse and minimally validate one exact-runner status line."""

    lines = [line for line in output.splitlines() if "frame_hex=" in line]
    if len(lines) != 1:
        raise ValueError("exact runner must emit one frame status line")
    fields = {
        match["key"]: match["value"]
        for match in FIELD_PATTERN.finditer(lines[0])
    }
    required = {
        "mode",
        "probe_id",
        "payload_size",
        "probe_size",
        "create_intercepts",
        "appvar_matches",
        "completed",
        "display_code",
        "frame_hex",
        "appvar_frame_hex",
    }
    missing = sorted(required - fields.keys())
    if missing:
        raise ValueError("exact runner omitted fields: " + ", ".join(missing))
    return fields


def validate_exact_capture(
    probe_name: str, fields: dict[str, str], machine_code_size: int
):
    """Validate one exact runner's frame identity and displayed CRC."""

    probe = PROBES[probe_name]
    if int(fields["probe_id"], 0) != probe.probe_id:
        raise ValueError("exact runner returned the wrong probe ID")
    if int(fields["payload_size"], 0) != probe.payload_size:
        raise ValueError("exact runner returned the wrong payload size")
    if int(fields["probe_size"], 0) != machine_code_size:
        raise ValueError("exact runner executed a different image size")
    staging_bytes = bytes.fromhex(fields["frame_hex"])
    resident_bytes = bytes.fromhex(fields["appvar_frame_hex"])
    staging_frame = decode_probe_frame(staging_bytes)
    resident_frame = decode_probe_frame(resident_bytes)
    if probe.probe_id == 4:
        if staging_bytes[:18] != resident_bytes[:18]:
            raise ValueError("execution AppVar changed an immutable frame field")
        before = staging_bytes[18]
        after = resident_bytes[18]
        transition_valid = (
            before == 0 and after in (1, 3, 4)
        ) or before == after in (2, 4)
        if not transition_valid:
            raise ValueError("execution AppVar has an invalid outcome transition")
        frame = resident_frame
    else:
        if fields["appvar_matches"] != "1" or resident_bytes != staging_bytes:
            raise ValueError("captured AppVar frame does not match probe staging data")
        frame = staging_frame
    code = probe_verification_code(frame)
    if int(fields["display_code"], 0) != code:
        raise ValueError("assembly display code does not match the captured frame")
    return frame, code


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("tilem", "wabbitemu"), required=True)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-binary-sha256", required=True)
    parser.add_argument("--probe", choices=DISPLAYED_PROBES, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--spasm", default="spasm")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    probe = PROBES[args.probe]
    try:
        require_output_absent(args.output_dir)
        rom_sha256 = require_exact_hash(
            args.rom, TI84_PLUS_OS_255MP_SHA256, "OS 2.55MP ROM"
        )
        binary_sha256 = require_exact_hash(
            args.binary, args.expected_binary_sha256, "exact runner"
        )
        machine_code = assemble_machine_code(args.probe, spasm=args.spasm)
        machine_sha256 = hashlib.sha256(machine_code).hexdigest()
        with tempfile.TemporaryDirectory(prefix="ti84-exact-probe-") as directory:
            machine_path = Path(directory) / f"{probe.program}.bin"
            machine_path.write_bytes(machine_code)
            completed = subprocess.run(
                [
                    str(args.binary),
                    "--exact-probe",
                    str(args.rom),
                    str(machine_path),
                    str(probe.probe_id),
                    str(probe.payload_size),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise ValueError(f"exact runner failed: {detail}")
        fields = parse_exact_output(completed.stdout)
        expected_mode = {
            "tilem": "tilem-exact-probe",
            "wabbitemu": "exact-probe",
        }[args.backend]
        if fields["mode"] != expected_mode or fields["completed"] != "1":
            raise ValueError("exact runner did not report a completed matching backend")
        frame, code = validate_exact_capture(args.probe, fields, len(machine_code))
        emulator = "TilEm" if args.backend == "tilem" else "Wabbitemu"
        commit = TILEM_COMMIT if args.backend == "tilem" else WABBITEMU_COMMIT
        result = {
            "emulator": emulator,
            "commit": commit,
            "backend": args.backend,
            "binary": str(args.binary),
            "binary_sha256": binary_sha256,
            "source_rom": str(args.rom),
            "source_rom_sha256": rom_sha256,
            "probe": args.probe,
            "program": probe.program,
            "result_appvar": probe.appvar,
            "machine_code_size": len(machine_code),
            "machine_code_sha256": machine_sha256,
            "native_fields": fields,
            "decoded_frame": {
                "probe_id": frame.probe_id,
                "asic_id": frame.asic_id,
                "status": frame.status,
                "payload_hex": frame.payload.hex().upper(),
                "verification_code_decimal": code,
                "measurements": decode_probe_measurements(frame),
            },
            "launch": (
                "retail-ROM boot and exact user-RAM injection"
                if args.backend == "wabbitemu"
                else "exact ROM load and guarded direct-Asm core baseline"
            ),
            "host_intercepts": (
                "_CreateAppVar is redirected to a private RAM buffer; execution "
                "stops at the first display bcall after the assembly CRC routine"
            ),
            "evidence_scope": (
                "exact assembled measurement, cleanup, frame update, and CRC; "
                "not TI-OS AppVar allocation, rendered screen pixels, or physical "
                "calculator behavior"
            ),
        }
        require_fresh_output_dir(args.output_dir)
        (args.output_dir / f"{probe.program}.bin").write_bytes(machine_code)
        manifest = write_json(args.output_dir / "manifest.json", result)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))
    emit_result(
        result,
        manifest,
        as_json=args.json,
        summary=(
            f"{emulator} {args.probe}: {result['decoded_frame']['measurements']}",
            f"verification code: {code}",
        ),
    )


if __name__ == "__main__":
    main()
