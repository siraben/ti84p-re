#!/usr/bin/env python3
"""Directly execute dormant retail-ROM LCD helpers through Wabbitemu."""

from __future__ import annotations

import argparse
from pathlib import Path

from ti84re.emulators.probe_cli import (
    DEFAULT_ROM,
    build_wabbitemu_result,
    emit_result,
    require_output_absent,
    write_manifest,
)
from ti84re.emulators.wabbitemu.headless import run_lcd_diagnostic_probe
from ti84re.emulators.wabbitemu.lcd_diagnostic_probe import validate_lcd_diagnostic_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-boot-steps", type=int, default=5_000_000)
    parser.add_argument("--max-probe-steps", type=int, default=250_000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        require_output_absent(args.output_dir)
        result = build_wabbitemu_result(
            binary=args.binary,
            source_rom=args.rom,
            runner=lambda binary, source_rom: run_lcd_diagnostic_probe(
                binary,
                source_rom,
                max_boot_steps=args.max_boot_steps,
                max_probe_steps=args.max_probe_steps,
            ),
            validator=validate_lcd_diagnostic_report,
            launch=(
                "direct entry from an injected RAM harness after retail boot "
                "establishes the protection baseline"
            ),
            evidence_scope=(
                "actual OS 2.55MP routines at 3F:74C6, 3F:46EF, 3F:472E, "
                "and 3F:74F8 executing in pinned Wabbitemu; not a reachable "
                "retail boot path or physical LCD/ASIC behavior"
            ),
        )
        manifest = write_manifest(args.output_dir, result)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))

    report = result["report"]
    native = report["native"]
    emit_result(
        result,
        manifest,
        as_json=args.json,
        summary=(
            f"fill={native['fill_hash']:016x} line={native['line_hash']:016x}; "
            f"writes={native['command_writes']} command/"
            f"{native['data_writes']} data",
            f"contrast command=0x{native['contrast_out']:02X}, "
            f"Wabbitemu level={native['contrast_level']}",
        ),
    )


if __name__ == "__main__":
    main()
