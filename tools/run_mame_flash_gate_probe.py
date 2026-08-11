#!/usr/bin/env python3
"""Run a guarded CPU-visible Flash-gate matrix through MAME 0.287."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from mame_flash_gate import (
    parse_flash_gate_report,
    validate_flash_gate_image,
    validate_flash_gate_report,
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

    script = TOOLS / "mame_flash_gate_probe.lua"
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
        report = validate_flash_gate_report(
            parse_flash_gate_report(run.combined_output)
        )
        flash_path = run.layout.rom_root / "nvram" / MACHINE / "flash"
        image = validate_flash_gate_image(args.rom, flash_path)
        result = {
            **run.manifest_fields(),
            "report": report,
            "flash_image": {"path": str(flash_path), **image},
            "launch": (
                "Lua maps Flash page 08 into the CPU program space and changes "
                "port 0x14 between AMD command phases"
            ),
            "evidence_scope": (
                "MAME 0.287 TI-84 Plus CPU and I/O mapping plus generic "
                "AMD_29F800T writes; not TI-OS execution or physical hardware"
            ),
        }
        manifest = args.output_dir / "manifest.json"
        manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, MameRuntimeError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(result, indent=2))
        return
    native_cases = report["native"]["cases"]
    print(
        "gate cases: "
        + ", ".join(
            f"{case['name']}={case['physical_byte']:02X}" for case in native_cases
        )
    )
    print(
        f"final Flash: {image['changed_byte_count']} changed byte, "
        f"SHA-256 {image['output_sha256']}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
