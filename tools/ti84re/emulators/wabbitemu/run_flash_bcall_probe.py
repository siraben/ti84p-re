#!/usr/bin/env python3
"""Assemble and run the programmer-facing Flash bcall examples."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from ti84re.flash.bcall_examples import (
    assemble_flash_bcall_probe,
    run_flash_bcall_usage_probe,
    validate_flash_bcall_usage_report,
)
from ti84re.emulators.probe_cli import (
    DEFAULT_ROM,
    emit_result,
    positive_int,
    require_fresh_output_dir,
    require_output_absent,
    wabbitemu_identity,
    write_json,
)
from ti84re.emulators.wabbitemu.headless import WabbitemuHeadlessError, file_sha256
from ti84re.paths import PROBES

DEFAULT_SOURCE = PROBES / "emulator" / "flash-bcall-usage.asm"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--spasm", default="spasm")
    parser.add_argument("--max-boot-steps", type=positive_int, default=5_000_000)
    parser.add_argument("--max-probe-steps", type=positive_int, default=250_000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        require_output_absent(args.output_dir)
        identity = wabbitemu_identity(args.binary, args.rom)
        with tempfile.TemporaryDirectory(prefix="ti84-flash-bcall-usage-") as temp_dir:
            machine_code = Path(temp_dir) / "flash-bcall-usage.bin"
            assemble_command = assemble_flash_bcall_probe(
                args.source,
                machine_code,
                spasm=args.spasm,
            )
            report = validate_flash_bcall_usage_report(
                run_flash_bcall_usage_probe(
                    args.binary,
                    args.rom,
                    machine_code,
                    max_boot_steps=args.max_boot_steps,
                    max_probe_steps=args.max_probe_steps,
                )
            )
            machine_code_bytes = machine_code.read_bytes()
        result = {
            **identity,
            "assembly_source": str(args.source),
            "assembly_source_sha256": file_sha256(args.source),
            "machine_code_sha256": report["native"]["machine_code_sha256"],
            "assemble_command": assemble_command,
            "report": report,
            "launch": (
                "retail boot establishes protection state; an assembled RAM "
                "program invokes every public modifying Flash bcall, "
                "_SetFlashLowerBound, and _FlashToRam through the original ROM"
            ),
            "evidence_scope": (
                "pinned Wabbitemu and exact retail-ROM bcall execution with a "
                "directly opened in-memory emulator gate; not the protected "
                "unlock sequence, OS allocation/journaling, power loss, or "
                "physical Flash"
            ),
        }
        require_fresh_output_dir(args.output_dir)
        (args.output_dir / "flash-bcall-usage.bin").write_bytes(machine_code_bytes)
        manifest = write_json(args.output_dir / "manifest.json", result)
    except (OSError, ValueError, WabbitemuHeadlessError) as error:
        parser.error(str(error))

    native = report["native"]
    emit_result(
        result,
        manifest,
        as_json=args.json,
        summary=[
            "bcalls: "
            f"write-safe={native['writeflash_visits']}, "
            f"write-core={native['writeflashunsafe_visits']}, "
            f"byte-safe={native['writeabytesafe_visits']}, "
            f"byte-core={native['writeabyte_visits']}, "
            f"erase-page={native['erasepage_visits']}, "
            f"erase-core={native['eraseflash_visits']}, "
            f"erase-cert={native['erasecertificate_visits']}, "
            f"bound={native['setbound_visits']}, "
            f"read={native['flashtoram_visits']}"
        ],
    )


if __name__ == "__main__":
    main()
