#!/usr/bin/env python3
"""Run guarded CPU-speed and delay-register edges through pinned Wabbitemu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    file_sha256,
    run_speed_edge_probe,
)
from wabbitemu_speed_probe import validate_speed_report


TOOLS = Path(__file__).resolve().parent
DEFAULT_ROM = TOOLS / "rom.bin"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.output_dir.exists():
        parser.error(f"refusing to reuse existing output directory {args.output_dir}")
    try:
        source_rom_sha256 = file_sha256(args.rom)
        if source_rom_sha256 != TI84_PLUS_OS_255MP_SHA256:
            raise ValueError("probe requires the exact local OS 2.55MP ROM")
        report = validate_speed_report(run_speed_edge_probe(args.binary, args.rom))
        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": file_sha256(args.binary),
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
            "report": report,
            "launch": "direct initialized-core speed and delay-register port calls",
            "evidence_scope": (
                "pinned Wabbitemu speed masks, internal extra-speed configuration, "
                "raw delay latches, wait-gate selection, and port-0x2D handler side "
                "effects; not retail-ROM execution, host timing, electrical timing, "
                "or physical low-power behavior"
            ),
        }
        args.output_dir.mkdir(parents=True)
        manifest = args.output_dir / "manifest.json"
        manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError, WabbitemuHeadlessError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(result, indent=2))
        return
    native = report["native"]
    print(
        "default modes: "
        + "/".join(str(value) for value in native["default_speed_reads"])
        + "; front-end modes: "
        + "/".join(str(value) for value in native["extra_speed_reads"])
    )
    print(
        "wait masks: "
        + "/".join(f"{value:02X}" for value in native["wait_masks"])
        + f"; port 2D readback={native['port2d_read']:02X}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
