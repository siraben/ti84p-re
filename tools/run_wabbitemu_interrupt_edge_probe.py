#!/usr/bin/env python3
"""Run guarded interrupt-controller edges through pinned Wabbitemu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    file_sha256,
    run_interrupt_edge_probe,
)
from wabbitemu_interrupt_probe import validate_interrupt_report


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
        report = validate_interrupt_report(
            run_interrupt_edge_probe(args.binary, args.rom)
        )
        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": file_sha256(args.binary),
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
            "report": report,
            "launch": "direct initialized-core interrupt and low-power port calls",
            "evidence_scope": (
                "pinned Wabbitemu mask, ON latch, standard-timer rate and "
                "boundary, acknowledgement, programmable-completion, and LCD "
                "low-power behavior; not TI-OS execution, wall-clock timing, "
                "physical interrupt edges, or ASIC power-domain evidence"
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
        f"mask: {native['initial_mask']:02X}→{native['stored_mask']:02X}; "
        f"ON ack={int(native['on_latch_before_ack'])}→"
        f"{int(native['on_latch_after_ack'])}"
    )
    print(
        f"timer boundary: {native['exact_boundary_status']:02X}→"
        f"{native['after_boundary_status']:02X}; "
        f"port-3/port-2 ack={native['after_port3_ack_status']:02X}/"
        f"{native['after_port2_ack_status']:02X}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
