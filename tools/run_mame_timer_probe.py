#!/usr/bin/env python3
"""Run guarded programmable-timer and absent-RTC cases through MAME 0.287."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from mame_runtime import (
    MAME_VERSION,
    MameRuntimeError,
    run_guarded_probe,
    validate_rom_warning,
)
from mame_timer import parse_mame_timer_report, validate_mame_timer_report
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

    script = TOOLS / "mame_timer_probe.lua"
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
            seconds=2,
            lua_script=script,
            environment=os.environ,
        )
        validate_rom_warning(run.combined_output)
        report = validate_mame_timer_report(
            parse_mame_timer_report(run.combined_output)
        )
        result = {
            **run.manifest_fields(),
            "report": report,
            "launch": (
                "Lua parks the CPU in isolated RAM, drives timer registers "
                "through CPU I/O space, and advances with machine frames"
            ),
            "evidence_scope": (
                "MAME 0.287 TI-84 Plus programmable-timer callbacks, status, "
                "and absent RTC mapping; not TI-OS timing or physical hardware"
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
        "fixed-crystal counts: "
        + ", ".join(f"{value:02X}" for value in native["family_counts"])
        + f" after {native['family_elapsed_attoseconds']} attoseconds"
    )
    print(
        "expiry: "
        f"zero={native['zero_count']:02X}, "
        f"bit1-set-port4={native['bit1_set_port4']:02X}, "
        f"bit1-clear-port4={native['bit1_clear_port4']:02X}, "
        f"loop-final={native['loop_count']:02X}"
    )
    print(
        f"global completion clear: {native['global_before']:02X}→"
        f"{native['global_after']:02X}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
