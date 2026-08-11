#!/usr/bin/env python3
"""Run guarded RAM execution-protection probes under pinned TilEm."""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import asdict
from pathlib import Path

from execution_protection import (
    PAGE_SIZE,
    TI84P_BOOT_PROTECTION,
    tilem_ram_execution_allowed,
    wabbitemu_ram_execution_allowed,
)
from execution_protection_fixture import (
    RamExecutionTarget,
    analyze_ram_execution_trace,
    assemble_ram_probe,
    build_tilem_ram_execution_fixture,
    file_digest,
)
from probe_cli import emit_result, require_fresh_output_dir, write_json

TOOLS = Path(__file__).resolve().parent
SOURCE = TOOLS / "emulator-probes" / "execution-protection-ram-tilem.asm"
MACRO = TOOLS / "macros" / "run-first-program.macro"
DEFAULT_ROM = TOOLS / "rom.bin"
DEFAULT_TARGETS = (
    RamExecutionTarget(0, 2, 0x03F0),
    RamExecutionTarget(0, 2, 0x0400),
    RamExecutionTarget(1, 2, 0x03F0),
    RamExecutionTarget(1, 2, 0x0400),
    RamExecutionTarget(1, 5, 0x3FF0),
    RamExecutionTarget(1, 6, 0x03F0),
)


def target(value: str) -> RamExecutionTarget:
    try:
        mode_text, page_text, offset_text = value.split(":")
        return RamExecutionTarget(
            int(mode_text, 0),
            int(page_text, 0),
            int(offset_text, 0),
        )
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "target must have MODE:PHYSICAL_PAGE:PAGE_OFFSET form"
        ) from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--tilem", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--target",
        type=target,
        action="append",
        help="custom MODE:PHYSICAL_PAGE:PAGE_OFFSET point; repeat as needed",
    )
    parser.add_argument("--spasm", default="spasm")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    targets = tuple(args.target) if args.target else DEFAULT_TARGETS
    if len(set(targets)) != len(targets):
        parser.error("each RAM target may be specified only once")
    try:
        source_rom = args.rom.read_bytes()
        require_fresh_output_dir(args.output_dir)
        reports = []
        for item in targets:
            machine_path = args.output_dir / f"{item.name}.bin"
            machine_code = assemble_ram_probe(
                SOURCE,
                item.physical_page,
                item.page_offset,
                item.marker,
                machine_path,
                spasm=args.spasm,
            )
            fixture = build_tilem_ram_execution_fixture(
                source_rom,
                machine_code,
                item.mode,
                item.physical_page,
                item.page_offset,
                item.marker,
            )
            rom_path = args.output_dir / f"{item.name}.rom"
            program_path = args.output_dir / f"{fixture.program_name}.8xp"
            runner_path = args.output_dir / f"{fixture.runner_name}.8xp"
            trace_path = args.output_dir / f"{item.name}.trace"
            log_path = args.output_dir / f"{item.name}.log"
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
                    f"TilEm failed for {item.name}; see {log_path}"
                )
            trace = analyze_ram_execution_trace(trace_path, fixture)
            tilem_allowed = tilem_ram_execution_allowed(
                item.physical_page * PAGE_SIZE + item.page_offset,
                item.mode,
                TI84P_BOOT_PROTECTION.ram_lower_chunk,
                TI84P_BOOT_PROTECTION.ram_upper_chunk,
            )
            wabbitemu_allowed = wabbitemu_ram_execution_allowed(
                item.physical_page,
                item.page_offset,
                item.mode,
                TI84P_BOOT_PROTECTION.ram_lower_chunk,
                TI84P_BOOT_PROTECTION.ram_upper_chunk,
            )
            expected = "returned" if tilem_allowed else "violation-reset"
            if trace.classification != expected:
                raise RuntimeError(
                    f"{item.name}: observed {trace.classification}, expected {expected}"
                )
            warning_count = completed.stderr.count(
                "Executing in restricted RAM area"
            )
            expected_warnings = 0 if tilem_allowed else 1
            if warning_count != expected_warnings:
                raise RuntimeError(
                    f"{item.name}: observed {warning_count} restricted-RAM "
                    f"warning(s), expected {expected_warnings}"
                )
            reports.append(
                {
                    "name": item.name,
                    "mode": item.mode,
                    "physical_page": item.physical_page,
                    "selector": 0x80 | item.physical_page,
                    "page_offset": item.page_offset,
                    "tilem_expected": expected,
                    "wabbitemu_source_prediction": (
                        "returned" if wabbitemu_allowed else "violation-reset"
                    ),
                    "predicates_agree": tilem_allowed == wabbitemu_allowed,
                    "source_rom_sha256": fixture.source_rom_sha256,
                    "fixture_rom_sha256": fixture.fixture_rom_sha256,
                    "machine_code_sha256": fixture.probe.machine_code_sha256,
                    "trace": asdict(trace),
                    "restricted_warning_count": warning_count,
                }
            )

        result = {
            "emulator": str(args.tilem),
            "emulator_sha256": file_digest(args.tilem),
            "source": str(SOURCE),
            "source_sha256": file_digest(SOURCE),
            "bounds": {
                "lower_chunk": TI84P_BOOT_PROTECTION.ram_lower_chunk,
                "upper_chunk": TI84P_BOOT_PROTECTION.ram_upper_chunk,
            },
            "targets": reports,
            "launch": (
                "the exact ROM changes only the boot port-0x21 immediate; "
                "the OS launches a self-installing guarded RAM probe"
            ),
            "evidence_scope": (
                "pinned TilEm behavior and Wabbitemu source predictions; "
                "not physical ASIC behavior"
            ),
        }
        manifest = args.output_dir / "manifest.json"
        write_json(manifest, result)
    except (OSError, RuntimeError, ValueError) as error:
        parser.error(str(error))

    emit_result(
        result,
        manifest,
        as_json=args.json,
        summary=(
            f"mode {item['mode']} page {item['selector']:02X} "
            f"offset {item['page_offset']:04X}: {trace['classification']} "
            f"({comparison})"
            for item in reports
            for trace in (item["trace"],)
            for comparison in (
                "agree" if item["predicates_agree"] else "differs from Wabbitemu",
            )
        )
    )


if __name__ == "__main__":
    main()
