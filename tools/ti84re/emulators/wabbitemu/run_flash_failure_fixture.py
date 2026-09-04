#!/usr/bin/env python3
"""Run guarded Flash preflight, DQ5-failure, and restart fixtures."""

from __future__ import annotations

import argparse
from pathlib import Path

from ti84re.file_hashes import file_sha256
from ti84re.emulators.probe_cli import (
    DEFAULT_ROM,
    emit_result,
    positive_int,
    require_output_absent,
    wabbitemu_identity,
    write_manifest,
)
from ti84re.emulators.wabbitemu.flash_probe import (
    FlashProgramCase,
    validate_flash_preflight_report,
    validate_worker_report,
)
from ti84re.emulators.wabbitemu.headless import (
    WabbitemuHeadlessError,
    run_flash_preflight_probe,
    run_flash_worker_probe,
)

LEGAL_CONTROL = FlashProgramCase(0xFF, 0x50)
DQ5_FAILURE = FlashProgramCase(0x50, 0xD0)


def validate_probe_inputs(
    source_rom: Path,
    binary: Path,
    expected_binary_sha256: str,
) -> dict[str, object]:
    """Require the exact retail ROM and explicitly pinned native adapter."""

    return wabbitemu_identity(
        binary,
        source_rom,
        expected_binary_sha256=expected_binary_sha256,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-binary-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-boot-steps", type=positive_int, default=5_000_000)
    parser.add_argument("--max-probe-steps", type=positive_int, default=10_000)
    parser.add_argument("--max-restart-steps", type=positive_int, default=5_000_000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        require_output_absent(args.output_dir)
        identity = validate_probe_inputs(
            args.rom,
            args.binary,
            args.expected_binary_sha256,
        )
        source_hash_before = file_sha256(args.rom)
        preflight = validate_flash_preflight_report(
            run_flash_preflight_probe(
                args.binary,
                args.rom,
                max_boot_steps=args.max_boot_steps,
                max_probe_steps=args.max_probe_steps,
                max_restart_steps=args.max_restart_steps,
            )
        )
        controls = []
        for case in (LEGAL_CONTROL, DQ5_FAILURE):
            controls.append(
                validate_worker_report(
                    case,
                    run_flash_worker_probe(
                        args.binary,
                        args.rom,
                        case.initial,
                        case.requested,
                        initial_toggle=case.initial_toggle,
                        max_boot_steps=args.max_boot_steps,
                        max_probe_steps=args.max_probe_steps,
                    ),
                )
            )
        source_hash_after = file_sha256(args.rom)
        if source_hash_after != source_hash_before:
            raise WabbitemuHeadlessError(
                "source ROM changed while running the disposable Flash fixture"
            )
        failure = controls[1]["native"]
        if failure["classification"] != "failure" or failure["return_af"] != 0x3F2C:
            raise WabbitemuHeadlessError(
                "DQ5 fixture did not return the expected numeric NZ status"
            )
        result = {
            **identity,
            "numeric_status": preflight["numeric_status"],
            "source_rom_sha256_after": source_hash_after,
            "source_rom_unchanged": True,
            "preflight_reset_restart": preflight,
            "worker_cases": controls,
            "safety": {
                "source_file_mode": "read-only input; no output ROM is written",
                "mutation_lifetime": "allocated Wabbitemu Flash array only",
                "allowed_target": controls[0]["target_guard"],
                "forbidden_targets": "OS, certificate, and boot pages",
                "physical_device": "not used",
            },
            "interruption_limit": (
                "Wabbitemu completes byte programming immediately; this fixture "
                "tests reset after the no-write preflight failure, not a cut "
                "inside a physical busy interval"
            ),
        }
        manifest = write_manifest(args.output_dir, result)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))

    emit_result(
        result,
        manifest,
        as_json=args.json,
        summary=[
            f"status={preflight['numeric_status']}",
            "preflight: reset=1, flash changes=0, retail restart=1",
            (
                "DQ5 worker: reads "
                f"{' '.join(f'{value:02X}' for value in failure['poll_reads'])}, "
                f"stored {failure['stored']:02X}, AF={failure['return_af']:04X}"
            ),
            "source ROM changed bytes=0; physical device writes=0",
        ],
    )


if __name__ == "__main__":
    main()
