#!/usr/bin/env python3
"""Run the assembled physical prefix-M1 program through pinned Wabbitemu."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from build_hardware_probes import assemble_machine_code
from hardware_probe import decode_probe_frame, decode_probe_measurements
from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    file_sha256,
    run_prefix_m1_probe,
)

TOOLS = Path(__file__).resolve().parent
DEFAULT_ROM = TOOLS / "rom.bin"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-binary-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--spasm", default="spasm")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error(f"refusing to reuse existing output directory {args.output_dir}")
    try:
        source_rom_sha256 = file_sha256(args.rom)
        if source_rom_sha256 != TI84_PLUS_OS_255MP_SHA256:
            raise ValueError("probe requires the exact local OS 2.55MP ROM")
        binary_sha256 = file_sha256(args.binary)
        if binary_sha256 != args.expected_binary_sha256.lower():
            raise ValueError(
                f"binary SHA-256 is {binary_sha256}; "
                f"expected {args.expected_binary_sha256.lower()}"
            )
        machine_code = assemble_machine_code("prefix-m1", spasm=args.spasm)
        with tempfile.TemporaryDirectory(prefix="ti84-prefix-m1-") as directory:
            machine_path = Path(directory) / "HWPFX.bin"
            machine_path.write_bytes(machine_code)
            native = run_prefix_m1_probe(args.binary, args.rom, machine_path)
        frame = decode_probe_frame(bytes.fromhex(native.frame_hex))
        if frame.probe_id != 11:
            raise ValueError(f"native frame has probe ID {frame.probe_id}, expected 11")
        decoded = decode_probe_measurements(frame)
        discriminator = decoded["measurements"]["indexed_cb_discriminator"]
        if discriminator["closer_to"] != "wabbitemu-three-m1":
            raise ValueError(
                "assembled runtime did not reproduce Wabbitemu's indexed-CB model"
            )
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
                "retail boot followed by exact HWPFX machine-code injection into "
                "logical user RAM; execution stops before _CreateAppVar"
            ),
            "evidence_scope": (
                "assembled probe control flow, timer samples, cleanup, and pinned "
                "Wabbitemu prefix-wait behavior; not OS variable creation, host "
                "wall time, electrical timing, or physical ASIC behavior"
            ),
        }
        args.output_dir.mkdir(parents=True)
        (args.output_dir / "HWPFX.bin").write_bytes(machine_code)
        manifest = args.output_dir / "manifest.json"
        manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError, WabbitemuHeadlessError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(result, indent=2))
        return
    print(
        "indexed CB: "
        + result["decoded_frame"]["measurements"]["measurements"]
        ["indexed_cb_discriminator"]["closer_to"]
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
