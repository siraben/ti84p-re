#!/usr/bin/env python3
"""Run a guarded sector-geometry and chip-erase matrix through MAME 0.287."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from mame_flash_erase import (
    parse_flash_erase_report,
    validate_erased_flash_image,
    validate_flash_erase_report,
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

    script = TOOLS / "mame_flash_erase_probe.lua"
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
            seconds=25,
            lua_script=script,
            environment=os.environ,
        )
        validate_rom_warning(run.combined_output)
        report = validate_flash_erase_report(
            parse_flash_erase_report(run.combined_output)
        )
        flash_path = run.layout.rom_root / "nvram" / MACHINE / "flash"
        image = validate_erased_flash_image(args.rom, flash_path)
        result = {
            **run.manifest_fields(),
            "report": report,
            "flash_image": {"path": str(flash_path), **image},
            "launch": (
                "Lua sequences five sector erases and one chip erase through "
                "the TI-84 Plus membank0 Flash interface"
            ),
            "evidence_scope": (
                "MAME 0.287 generic AMD_29F800T erase geometry, status range, "
                "timers, and TI-84 Plus mapping; not TI-OS or physical hardware"
            ),
        }
        manifest = args.output_dir / "manifest.json"
        manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, MameRuntimeError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(result, indent=2))
        return
    print("sector cases: regular64, top32, top8a, top8b, top16")
    print(
        f"chip erase: {image['changed_byte_count']} changed bytes, "
        f"SHA-256 {image['output_sha256']}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
