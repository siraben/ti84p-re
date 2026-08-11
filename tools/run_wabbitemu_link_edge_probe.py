#!/usr/bin/env python3
"""Run guarded raw-link and link-assist edges through pinned Wabbitemu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    file_sha256,
    run_link_edge_probe,
)
from wabbitemu_link_probe import validate_link_report


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
        report = validate_link_report(run_link_edge_probe(args.binary, args.rom))
        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": file_sha256(args.binary),
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
            "report": report,
            "launch": "direct initialized-core raw-link and assist port calls",
            "evidence_scope": (
                "pinned Wabbitemu raw truth table, mapped assist ports, status, "
                "interrupt, LSB-first send/receive, and read-to-clear behavior; "
                "not TI-OS execution, virtual-cable lifecycle, electrical levels, "
                "physical edge timing, or connected-calculator evidence"
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
        "raw rows: "
        + " / ".join(
            ",".join(f"{value:02X}" for value in native["raw_reads"][start:start + 4])
            for start in range(0, 16, 4)
        )
    )
    print(
        f"assist: send={native['assist_send_out']:02X}/"
        f"{native['assist_send_status']:02X}, "
        f"receive={native['assist_receive_in']:02X}/"
        f"{native['assist_receive_status']:02X}, "
        f"error={native['assist_error_status']:02X}→"
        f"{native['assist_error_after_read_status']:02X}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
