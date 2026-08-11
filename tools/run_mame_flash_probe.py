#!/usr/bin/env python3
"""Run a binary-guarded Flash command/status matrix through MAME 0.287."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from mame_flash import (
    MAME_FLASH_IMAGE_SHA256,
    parse_flash_report,
    validate_flash_image,
    validate_flash_report,
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

    script = TOOLS / "mame_flash_probe.lua"
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
        report = validate_flash_report(parse_flash_report(run.combined_output))
        flash_path = run.layout.rom_root / "nvram" / MACHINE / "flash"
        image = validate_flash_image(
            args.rom,
            flash_path,
            expected_sha256=MAME_FLASH_IMAGE_SHA256,
        )
        result = {
            **run.manifest_fields(),
            "report": report,
            "flash_image": {"path": str(flash_path), **image},
            "launch": (
                "Lua writes and reads the TI-84 Plus membank0 Flash interface; "
                "MAME persists the complete final array to isolated NVRAM"
            ),
            "evidence_scope": (
                "MAME 0.287 generic AMD_29F800T and TI-84 Plus mapping behavior; "
                "not TI-OS Flash routines or physical hardware"
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
        "program: "
        f"FF->50={native['legal_stored']:02X}, "
        f"50->D0={native['illegal_stored']:02X}"
    )
    print(
        "top-sector busy reads: "
        f"selected {native['busy_selected']}, "
        f"adjacent {native['busy_adjacent']:02X}, boot {native['busy_boot']:02X}"
    )
    print(
        f"final Flash: {image['changed_byte_count']} changed bytes, "
        f"SHA-256 {image['output_sha256']}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
