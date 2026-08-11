#!/usr/bin/env python3
"""Run the controlled retail USB installer-record probe."""

from __future__ import annotations

import argparse
from pathlib import Path

from probe_cli import (
    DEFAULT_ROM,
    emit_result,
    require_output_absent,
    write_manifest,
)
from probe_cli import validate_wabbitemu_probe_inputs as validate_probe_inputs
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    run_usb_rom_receive_probe,
)
from wabbitemu_usb_receive import validate_usb_rom_receive_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-binary-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        require_output_absent(args.output_dir)
        source_rom_sha256, binary_sha256 = validate_probe_inputs(
            args.rom, args.binary, args.expected_binary_sha256
        )
        report = validate_usb_rom_receive_report(
            run_usb_rom_receive_probe(args.binary, args.rom)
        )
        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": binary_sha256,
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
            "report": report,
        }
        manifest = write_manifest(args.output_dir, result)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))

    runtime = report["runtime"]
    emit_result(
        result,
        manifest,
        as_json=args.json,
        summary=(
            "USB receive: rejected page "
            f"0x{runtime['page_check_value']:02X} after {runtime['probe_steps']} "
            f"instructions; Flash changes={runtime['flash_changed_bytes']}",
        ),
    )


if __name__ == "__main__":
    main()
