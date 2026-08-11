#!/usr/bin/env python3
"""Build and run guarded Flash execution-boundary probes under TilEm."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from execution_protection import (
    TI84P_BOOT_PROTECTION,
    tilem_flash_execution_allowed,
)
from execution_protection_fixture import (
    analyze_flash_execution_trace,
    assemble_probe,
    build_flash_execution_fixture,
    file_digest,
)


TOOLS = Path(__file__).resolve().parent
SOURCE = TOOLS / "emulator-probes" / "execution-protection-flash.asm"
MACRO = TOOLS / "macros" / "run-first-program.macro"
DEFAULT_ROM = TOOLS / "rom.bin"
DEFAULT_PAGES = (0x07, 0x08, 0x29, 0x2A)


def byte(value: str) -> int:
    parsed = int(value, 0)
    if not 0 <= parsed <= 0x3F:
        raise argparse.ArgumentTypeError("page must be between 0x00 and 0x3F")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--tilem", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--page", type=byte, action="append")
    parser.add_argument("--spasm", default="spasm")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    pages = tuple(args.page) if args.page else DEFAULT_PAGES
    if len(set(pages)) != len(pages):
        parser.error("each --page may be specified only once")
    if args.output_dir.exists():
        parser.error(f"refusing to reuse existing output directory {args.output_dir}")

    try:
        source_rom = args.rom.read_bytes()
        args.output_dir.mkdir(parents=True)
        reports = []
        for page in pages:
            stem = f"page-{page:02x}"
            machine_path = args.output_dir / f"{stem}.bin"
            machine_code = assemble_probe(
                SOURCE,
                page,
                machine_path,
                spasm=args.spasm,
            )
            fixture = build_flash_execution_fixture(source_rom, machine_code, page)
            rom_path = args.output_dir / f"{stem}.rom"
            program_path = args.output_dir / f"{fixture.program_name}.8xp"
            runner_path = args.output_dir / f"{fixture.runner_name}.8xp"
            trace_path = args.output_dir / f"{stem}.trace"
            log_path = args.output_dir / f"{stem}.log"
            rom_path.write_bytes(fixture.rom)
            program_path.write_bytes(fixture.program)
            runner_path.write_bytes(fixture.runner)

            completed = subprocess.run(
                [
                    str(args.tilem),
                    "--headless",
                    "--rom",
                    str(rom_path),
                    "--model",
                    "ti84p",
                    "--normal-speed",
                    "--reset",
                    "--macro",
                    str(MACRO),
                    "--trace",
                    str(trace_path),
                    "--trace-range",
                    "all",
                    str(runner_path),
                    str(program_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
            if completed.returncode:
                raise RuntimeError(
                    f"TilEm failed for page 0x{page:02X}; see {log_path}"
                )
            result = analyze_flash_execution_trace(trace_path, fixture)
            expected = (
                "returned"
                if tilem_flash_execution_allowed(
                    page,
                    TI84P_BOOT_PROTECTION.flash_lower,
                    TI84P_BOOT_PROTECTION.flash_upper,
                )
                else "violation-reset"
            )
            if result.classification != expected:
                raise RuntimeError(
                    f"page 0x{page:02X}: observed {result.classification}, "
                    f"expected {expected}"
                )
            warning_count = completed.stderr.count(
                "Executing in restricted Flash area"
            )
            expected_warnings = 0 if expected == "returned" else 1
            if warning_count != expected_warnings:
                raise RuntimeError(
                    f"page 0x{page:02X}: observed {warning_count} restricted "
                    f"warning(s), expected {expected_warnings}"
                )
            reports.append(
                {
                    "page": page,
                    "expected": expected,
                    "source_rom_sha256": fixture.source_rom_sha256,
                    "fixture_rom_sha256": fixture.fixture_rom_sha256,
                    "machine_code_sha256": fixture.machine_code_sha256,
                    "call_address": fixture.call_address,
                    "return_address": fixture.return_address,
                    "trace": asdict(result),
                    "restricted_warning_count": warning_count,
                }
            )
        report = {
            "emulator": str(args.tilem),
            "emulator_sha256": file_digest(args.tilem),
            "source": str(SOURCE),
            "source_sha256": file_digest(SOURCE),
            "bounds": {
                "lower": TI84P_BOOT_PROTECTION.flash_lower,
                "upper": TI84P_BOOT_PROTECTION.flash_upper,
            },
            "pages": reports,
            "evidence_scope": "pinned TilEm behavior; not physical ASIC behavior",
        }
        manifest = args.output_dir / "manifest.json"
        manifest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(report, indent=2))
        return
    for item in reports:
        trace = item["trace"]
        print(
            f"page {item['page']:02X}: {trace['classification']} "
            f"call={trace['call_clock']} target={trace['target_clock']} "
            f"return={trace['return_clock']} reset={trace['reset_clock']}"
        )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
