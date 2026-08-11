#!/usr/bin/env python3
"""Run guarded TI-84 Plus ASIC-control cases through MAME 0.287."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from mame_asic import parse_mame_asic_report, validate_mame_asic_report
from mame_runtime import (
    MAME_VERSION,
    MameRuntimeError,
    run_guarded_probe,
    validate_rom_warning,
)
from rom_signatures import TI84_PLUS_OS_255MP_SHA256

TOOLS = Path(__file__).resolve().parent
DEFAULT_ROM = TOOLS / "rom.bin"
MACHINE = "ti84pv3"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--mame", default="mame")
    parser.add_argument("--expected-mame-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    script = TOOLS / "mame_asic_probe.lua"
    try:
        run = run_guarded_probe(
            executable=args.mame,
            expected_executable_sha256=args.expected_mame_sha256,
            expected_version=MAME_VERSION,
            machine=MACHINE,
            source_rom=args.rom,
            expected_rom_sha256=TI84_PLUS_OS_255MP_SHA256,
            rom_description="the exact local OS 2.55MP ROM",
            output_dir=args.output_dir,
            seconds=4,
            lua_script=script,
            environment=os.environ,
        )
        validate_rom_warning(run.combined_output)
        report = validate_mame_asic_report(parse_mame_asic_report(run.combined_output))
        result = {
            **run.manifest_fields(),
            "report": report,
            "launch": (
                "Lua drives mapped and absent I/O through the CPU space, runs a "
                "50-T-state RAM counter at both clocks, and schedules a soft reset"
            ),
            "evidence_scope": (
                "MAME 0.287 TI-84 Plus status, raw Flash-gate byte, speed clock, "
                "port-0x21 mask, absent protection/GPIO ports, disconnected USB "
                "constants, and soft-reset retention; not physical ASIC behavior"
            ),
        }
        manifest = args.output_dir / "manifest.json"
        manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, MameRuntimeError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(result, indent=2))
        return
    native = report["native"]
    print(
        "gate status: "
        + "/".join(f"{value:02X}" for value in native["gate_status"])
        + "; port 14 remains write-only"
    )
    print(
        f"clock loop: {native['clock_low_count']}→{native['clock_high_count']} "
        f"in {native['clock_low_attoseconds'] / 1e18:.1f} s; "
        f"soft reset retains 14/20/21={native['soft_status02']:02X}/"
        f"{native['soft_speed20']:02X}/{native['soft_control21']:02X}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
