#!/usr/bin/env python3
"""Run a guarded live-input keypad matrix through MAME 0.287."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from mame_keypad import parse_mame_keypad_report, validate_mame_keypad_report
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

    script = TOOLS / "mame_keypad_probe.lua"
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
        report = validate_mame_keypad_report(
            parse_mame_keypad_report(run.combined_output)
        )
        result = {
            **run.manifest_fields(),
            "report": report,
            "launch": (
                "Lua injects exact group/column fields through :BIT0-:BIT7 "
                "and reads port 0x01 through the main CPU I/O space"
            ),
            "evidence_scope": (
                "MAME 0.287 TI-84 Plus live input fields and keypad handlers; "
                "not TI-OS scanning, electrical settling, or physical hardware"
            ),
        }
        manifest = args.output_dir / "manifest.json"
        manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, MameRuntimeError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(result, indent=2))
        return
    native = {case["name"]: case for case in report["native"]["cases"]}
    print(
        "matrix reads: "
        f"single={native['single']['read']:02X}, "
        f"unselected={native['unselected']['read']:02X}, "
        f"same-column={native['same_column']['read']:02X}, "
        f"rectangle={native['rectangle']['read']:02X}"
    )
    print(
        "bounds: "
        f"bit-7-only={native['bit7_only']['read']:02X}, "
        f"column-7={native['column_seven']['read']:02X}, "
        f"all-selected={native['all_selected']['read']:02X}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
