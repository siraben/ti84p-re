#!/usr/bin/env python3
"""Run guarded reset-retention cases through pinned Wabbitemu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    file_sha256,
    run_reset_retention_probe,
)
from wabbitemu_reset import RETAINED_COMPONENTS, validate_reset_report


TOOLS = Path(__file__).resolve().parent
DEFAULT_ROM = TOOLS / "rom.bin"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--expected-binary-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.output_dir.exists():
        parser.error(f"refusing to reuse existing output directory {args.output_dir}")
    try:
        source_rom_sha256 = file_sha256(args.rom)
        if source_rom_sha256 != TI84_PLUS_OS_255MP_SHA256:
            raise ValueError("probe requires the exact local OS 2.55MP ROM")
        binary_sha256 = file_sha256(args.binary)
        if binary_sha256 != args.expected_binary_sha256.lower():
            raise ValueError(
                "native runner SHA-256 does not match --expected-binary-sha256"
            )
        report = validate_reset_report(
            run_reset_retention_probe(args.binary, args.rom)
        )
        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": binary_sha256,
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
            "report": report,
            "launch": (
                "direct initialized-core CPU_reset, frontend-equivalent LCD reset, "
                "and execution-violation CPU_step calls"
            ),
            "evidence_scope": (
                "pinned Wabbitemu reset implementation and directly seeded retention; "
                "not retail-ROM reset code, power-on ASIC defaults, or physical "
                "calculator retention"
            ),
        }
        args.output_dir.mkdir(parents=True)
        manifest = args.output_dir / "manifest.json"
        manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError, WabbitemuHeadlessError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(result, indent=2))
        return
    native = report["native"]
    retained_count = sum(native["retained"])
    print(
        f"CPU_reset retained {retained_count}/{len(RETAINED_COMPONENTS)} seeded "
        f"component groups; mapping="
        + "/".join(f"{page:02X}" for page in native["reset_pages"])
    )
    print(
        f"frontend LCD active={int(native['frontend_lcd_active'])}, "
        f"last_tstate={native['frontend_lcd_last_tstate']}; violation PCs="
        f"{native['program_violation_pc']:04X}/{native['error_violation_pc']:04X}"
    )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
