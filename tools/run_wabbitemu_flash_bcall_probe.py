#!/usr/bin/env python3
"""Assemble and run the programmer-facing Flash bcall examples."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from flash_bcall_examples import (
    assemble_flash_bcall_probe,
    run_flash_bcall_usage_probe,
    validate_flash_bcall_usage_report,
)
from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    file_sha256,
)

TOOLS = Path(__file__).resolve().parent
DEFAULT_ROM = TOOLS / "rom.bin"
DEFAULT_SOURCE = TOOLS / "emulator-probes" / "flash-bcall-usage.asm"


def positive_count(value: str) -> int:
    """Parse a positive instruction bound."""

    count = int(value, 0)
    if count <= 0:
        raise argparse.ArgumentTypeError("count must be positive")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--spasm", default="spasm")
    parser.add_argument("--max-boot-steps", type=positive_count, default=5_000_000)
    parser.add_argument("--max-probe-steps", type=positive_count, default=250_000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.output_dir.exists():
        parser.error(f"refusing to reuse existing output directory {args.output_dir}")
    try:
        source_rom_sha256 = file_sha256(args.rom)
        if source_rom_sha256 != TI84_PLUS_OS_255MP_SHA256:
            raise WabbitemuHeadlessError("probe requires the exact local OS 2.55MP ROM")
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
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": file_sha256(args.binary),
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
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
        args.output_dir.mkdir(parents=True)
        (args.output_dir / "flash-bcall-usage.bin").write_bytes(machine_code_bytes)
        manifest = args.output_dir / "manifest.json"
        manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, WabbitemuHeadlessError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(result, indent=2))
        return
    native = report["native"]
    print(
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
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
