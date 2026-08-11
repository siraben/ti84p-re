#!/usr/bin/env python3
"""Run guarded TI-84 Plus legacy-interrupt cases through MAME 0.287."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from mame_interrupt import (
    parse_mame_interrupt_report,
    validate_mame_interrupt_report,
)
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

    script = TOOLS / "mame_interrupt_probe.lua"
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
            seconds=5,
            lua_script=script,
            environment=os.environ,
        )
        validate_rom_warning(run.combined_output)
        report = validate_mame_interrupt_report(
            parse_mame_interrupt_report(run.combined_output)
        )
        result = {
            **run.manifest_fields(),
            "report": report,
            "launch": (
                "Lua parks the Z80 in DI RAM, drives :ON, accesses legacy "
                "interrupt ports through CPU I/O space, and schedules a soft reset"
            ),
            "evidence_scope": (
                "MAME 0.287 TI-84 Plus legacy status, mask, ON edge, fixed "
                "standard timers, and reset retention; not physical ASIC behavior"
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
        "status reads: "
        f"03={native['reset_status03']:02X}, 04={native['reset_status04']:02X}; "
        f"injected 07={native['injected_seed07']:02X}"
    )
    print(
        "ON edge: "
        f"masked={native['on_masked_press']:02X}, "
        f"enabled={native['on_enabled_press']:02X}, "
        f"released={native['on_enabled_release']:02X}"
    )
    print(
        "soft reset: "
        f"immediate={native['soft_immediate04']:02X}, "
        f"timers={native['soft_after_timers']:02X}, "
        f"ON={native['soft_after_on']:02X}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
