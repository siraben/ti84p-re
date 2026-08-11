#!/usr/bin/env python3
"""Run the assembled physical timer program through pinned Wabbitemu."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from build_hardware_probes import assemble_machine_code
from hardware_probe import decode_probe_frame, decode_probe_measurements
from probe_cli import (
    DEFAULT_ROM,
    emit_result,
    require_fresh_output_dir,
    require_output_absent,
    validate_wabbitemu_probe_inputs,
    write_json,
)
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    run_timer_physical_probe,
)


def validate_decoded_report(decoded: dict[str, object]) -> None:
    """Require the assembled run to reproduce pinned Wabbitemu timer edges."""

    measurements = decoded["measurements"]
    if measurements["crystal_divisor"]["closer_to"] != (
        "wabbitemu-and-mame-divisor-32"
    ):
        raise ValueError("runtime did not reproduce Wabbitemu's 0x41 divisor")
    mode3 = measurements["mode3_prescaler"]["cases"]
    if [row["actual_speed_mode"] for row in mode3] != [0, 1, 1, 1]:
        raise ValueError("runtime did not reproduce default speed-mode clamping")
    if any(
        row["closer_to"] != "emulator-no-prescaler" for row in mode3[1:]
    ):
        raise ValueError("runtime unexpectedly applied the port-0x2F prescaler")
    if measurements["counter_zero"]["closer_to"] != (
        "wabbitemu-completes-zero"
    ):
        raise ValueError("runtime did not reproduce Wabbitemu counter-zero expiry")
    if measurements["expiry_status"]["closer_to"] != (
        "wabbitemu-first-expiry"
    ):
        raise ValueError("runtime did not reproduce first-expiry status bit 2")
    if not all(decoded["restored"].values()):
        raise ValueError("assembled timer probe did not restore guarded state")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-binary-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--spasm", default="spasm")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        require_output_absent(args.output_dir)
        source_rom_sha256, binary_sha256 = validate_wabbitemu_probe_inputs(
            args.rom,
            args.binary,
            args.expected_binary_sha256,
        )
        machine_code = assemble_machine_code("timer-physical", spasm=args.spasm)
        with tempfile.TemporaryDirectory(prefix="ti84-timer-physical-") as directory:
            machine_path = Path(directory) / "HWTMR.bin"
            machine_path.write_bytes(machine_code)
            native = run_timer_physical_probe(
                args.binary,
                args.rom,
                machine_path,
            )
        frame = decode_probe_frame(bytes.fromhex(native.frame_hex))
        if frame.probe_id != 12:
            raise ValueError(f"native frame has probe ID {frame.probe_id}, expected 12")
        decoded = decode_probe_measurements(frame)
        validate_decoded_report(decoded)
        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": binary_sha256,
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
            "machine_code_size": len(machine_code),
            "machine_code_sha256": native.machine_code_sha256,
            "native": native.to_dict(),
            "decoded_frame": {
                "probe_id": frame.probe_id,
                "asic_id": frame.asic_id,
                "status": frame.status,
                "payload_hex": frame.payload.hex().upper(),
                "measurements": decoded,
            },
            "launch": (
                "retail boot followed by exact HWTMR machine-code injection into "
                "logical user RAM; execution stops before _CreateAppVar"
            ),
            "evidence_scope": (
                "assembled timer control flow, bounded polling, cleanup, and pinned "
                "Wabbitemu timer behavior; not OS variable creation, host wall time, "
                "crystal accuracy, electrical timing, or physical ASIC behavior"
            ),
        }
        require_fresh_output_dir(args.output_dir)
        (args.output_dir / "HWTMR.bin").write_bytes(machine_code)
        manifest = write_json(args.output_dir / "manifest.json", result)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))

    emit_result(
        result,
        manifest,
        as_json=args.json,
        summary=(
            "timer model: "
            + result["decoded_frame"]["measurements"]["measurements"]
            ["crystal_divisor"]["closer_to"],
        ),
    )


if __name__ == "__main__":
    main()
