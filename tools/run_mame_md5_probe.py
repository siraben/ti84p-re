#!/usr/bin/env python3
"""Run a guarded MD5-port coverage probe through MAME 0.287."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from mame_md5 import parse_mame_md5_report, validate_mame_md5_report
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

    script = TOOLS / "mame_md5_probe.lua"
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
        report = validate_mame_md5_report(
            parse_mame_md5_report(run.combined_output)
        )
        result = {
            **run.manifest_fields(),
            "report": report,
            "launch": (
                "Lua reads and writes ports 0x18-0x1F through the main CPU I/O "
                "space, then issues the first padded-abc MD5 transaction"
            ),
            "evidence_scope": (
                "MAME 0.287 TI-84 Plus I/O mapping and unmapped-port behavior; "
                "not TI-OS execution, MD5 hardware, or physical timing"
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
        "MD5 ports: initial and post-write reads are all zero; "
        f"valid step={native['observed_result']:08X} "
        f"(expected {native['expected_result']:08X})"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
