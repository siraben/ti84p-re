#!/usr/bin/env python3
"""Run controlled retail USB boot paths through pinned Wabbitemu."""

from __future__ import annotations

import argparse
from pathlib import Path

from ti84re.emulators.probe_cli import (
    DEFAULT_ROM,
    emit_result,
    require_output_absent,
    write_manifest,
)
from ti84re.emulators.probe_cli import validate_wabbitemu_probe_inputs as validate_probe_inputs
from ti84re.emulators.wabbitemu.headless import (
    WABBITEMU_COMMIT,
    run_usb_rom_probe,
)
from ti84re.emulators.wabbitemu.usb_rom import validate_usb_rom_reports


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
            args.rom,
            args.binary,
            args.expected_binary_sha256,
        )
        report = validate_usb_rom_reports(run_usb_rom_probe(args.binary, args.rom))
        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": binary_sha256,
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
            "report": report,
            "launch": (
                "retail boot followed by RAM-resident bcalls into untouched boot-page "
                "_InitUSB and _AttemptUSBOSReceive code"
            ),
            "evidence_scope": (
                "retail ROM dispatch, initialization, bounded handshake and frame "
                "timeouts, cleanup, event-0x40 dispatch, and absence of Flash writes "
                "under a controlled digital port harness; not a Wabbitemu USB-device "
                "model, endpoint payload transfer, electrical behavior, or physical "
                "calculator evidence"
            ),
        }
        manifest = write_manifest(args.output_dir, result)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))

    cases = {case["case"]: case for case in report["cases"]}
    emit_result(
        result,
        manifest,
        as_json=args.json,
        summary=(
            "USB ROM: success "
            f"{cases['init-success']['probe_steps']} instructions; "
            f"handshake timeout {cases['handshake-timeout']['input_4c']} polls; "
            f"frame timeout {cases['frame-timeout']['input_8c']} polls",
        ),
    )


if __name__ == "__main__":
    main()
