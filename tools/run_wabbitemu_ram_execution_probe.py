#!/usr/bin/env python3
"""Run guarded RAM execution-protection probes under pinned Wabbitemu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from execution_protection import (
    PAGE_SIZE,
    TI84P_BOOT_PROTECTION,
    tilem_ram_execution_allowed,
    wabbitemu_ram_execution_allowed,
)
from execution_protection_fixture import (
    PROGRAM_ORIGIN,
    RamExecutionTarget,
    assemble_ram_probe,
    build_ram_execution_probe,
    file_digest,
    validate_source_rom,
)
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    run_ram_execution_probe,
)


TOOLS = Path(__file__).resolve().parent
SOURCE = TOOLS / "emulator-probes" / "execution-protection-ram.asm"
DEFAULT_ROM = TOOLS / "rom.bin"


DEFAULT_TARGETS = (
    RamExecutionTarget(0, 1, 0x3FF0),
    RamExecutionTarget(0, 2, 0x03F0),
    RamExecutionTarget(0, 2, 0x0400),
    RamExecutionTarget(0, 3, 0x3FF0),
    RamExecutionTarget(0, 4, 0x0000),
    RamExecutionTarget(1, 1, 0x3FF0),
    RamExecutionTarget(1, 2, 0x03F0),
    RamExecutionTarget(1, 2, 0x0400),
    RamExecutionTarget(1, 5, 0x3FF0),
    RamExecutionTarget(1, 6, 0x03F0),
    RamExecutionTarget(2, 1, 0x3FF0),
    RamExecutionTarget(2, 2, 0x03F0),
    RamExecutionTarget(2, 2, 0x0400),
    RamExecutionTarget(2, 3, 0x0000),
    RamExecutionTarget(3, 1, 0x3FF0),
    RamExecutionTarget(3, 2, 0x03F0),
    RamExecutionTarget(3, 2, 0x0400),
    RamExecutionTarget(3, 3, 0x0000),
)


def byte(value: str) -> int:
    parsed = int(value, 0)
    if not 0 <= parsed <= 0xFF:
        raise argparse.ArgumentTypeError("value must be a byte")
    return parsed


def positive_count(value: str) -> int:
    count = int(value, 0)
    if count <= 0:
        raise argparse.ArgumentTypeError("count must be positive")
    return count


def target(value: str) -> RamExecutionTarget:
    try:
        mode_text, page_text, offset_text = value.split(":")
        item = RamExecutionTarget(
            int(mode_text, 0),
            int(page_text, 0),
            int(offset_text, 0),
        )
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "target must have MODE:PHYSICAL_PAGE:PAGE_OFFSET form"
        ) from error
    return item


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--target",
        type=target,
        action="append",
        help="custom MODE:PHYSICAL_PAGE:PAGE_OFFSET point; repeat as needed",
    )
    parser.add_argument(
        "--lower-chunk",
        type=byte,
        default=TI84P_BOOT_PROTECTION.ram_lower_chunk,
    )
    parser.add_argument(
        "--upper-chunk",
        type=byte,
        default=TI84P_BOOT_PROTECTION.ram_upper_chunk,
    )
    parser.add_argument("--spasm", default="spasm")
    parser.add_argument("--max-boot-steps", type=positive_count, default=5_000_000)
    parser.add_argument("--max-probe-steps", type=positive_count, default=1_000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    targets = tuple(args.target) if args.target else DEFAULT_TARGETS
    if len(set(targets)) != len(targets):
        parser.error("each RAM target may be specified only once")
    if args.output_dir.exists():
        parser.error(f"refusing to reuse existing output directory {args.output_dir}")

    try:
        source_rom = args.rom.read_bytes()
        source_rom_sha256 = validate_source_rom(source_rom)
        args.output_dir.mkdir(parents=True)
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
            fixture = build_ram_execution_probe(
                machine_code,
                item.physical_page,
                item.page_offset,
                item.marker,
            )
            report = run_ram_execution_probe(
                args.binary,
                args.rom,
                machine_path,
                item.physical_page,
                item.page_offset,
                item.mode,
                args.lower_chunk,
                args.upper_chunk,
                max_boot_steps=args.max_boot_steps,
                max_probe_steps=args.max_probe_steps,
            )
            wabbitemu_allowed = wabbitemu_ram_execution_allowed(
                item.physical_page,
                item.page_offset,
                item.mode,
                args.lower_chunk,
                args.upper_chunk,
            )
            tilem_allowed = tilem_ram_execution_allowed(
                item.physical_page * PAGE_SIZE + item.page_offset,
                item.mode,
                args.lower_chunk,
                args.upper_chunk,
            )
            expected = "returned" if wabbitemu_allowed else "violation-reset"
            if report.classification != expected:
                raise WabbitemuHeadlessError(
                    f"{item.name}: observed {report.classification}, expected {expected}"
                )
            if (report.call_address, report.return_address) != (
                fixture.call_address,
                fixture.return_address,
            ):
                raise WabbitemuHeadlessError(
                    f"{item.name}: native call addresses disagree with fixture"
                )
            if (report.source_page, report.source_address) != (1, PROGRAM_ORIGIN):
                raise WabbitemuHeadlessError(
                    f"{item.name}: native source mapping is unexpected"
                )
            expected_boot = (
                TI84P_BOOT_PROTECTION.ram_lower_chunk * 0x400,
                TI84P_BOOT_PROTECTION.ram_upper_chunk * 0x400 + 0x3FF,
                TI84P_BOOT_PROTECTION.ram_mode,
            )
            if (
                report.boot_ram_lower,
                report.boot_ram_upper,
                report.boot_ram_mode,
            ) != expected_boot:
                raise WabbitemuHeadlessError(
                    f"{item.name}: native boot-register snapshot is unexpected"
                )
            expected_configured = (
                (args.lower_chunk * 0x400) & 0xFFFF,
                (args.upper_chunk * 0x400 + 0x3FF) & 0xFFFF,
            )
            if (
                report.configured_ram_lower,
                report.configured_ram_upper,
            ) != expected_configured:
                raise WabbitemuHeadlessError(
                    f"{item.name}: native configured bounds are unexpected"
                )
            expected_marker = item.marker if wabbitemu_allowed else 0xA0
            if report.expected_marker != item.marker or report.marker != expected_marker:
                raise WabbitemuHeadlessError(
                    f"{item.name}: native marker result is unexpected"
                )
            reports.append(
                {
                    "name": item.name,
                    "mode": item.mode,
                    "physical_page": item.physical_page,
                    "selector": 0x80 | item.physical_page,
                    "page_offset": item.page_offset,
                    "wabbitemu_expected": expected,
                    "tilem_source_prediction": (
                        "returned" if tilem_allowed else "violation-reset"
                    ),
                    "predicates_agree": wabbitemu_allowed == tilem_allowed,
                    "machine_code_sha256": fixture.machine_code_sha256,
                    "native": report.to_dict(),
                }
            )

        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": file_digest(args.binary),
            "source_rom": str(args.rom),
            "source_rom_sha256": source_rom_sha256,
            "assembly_source": str(SOURCE),
            "assembly_source_sha256": file_digest(SOURCE),
            "configured_bounds": {
                "lower_chunk": args.lower_chunk,
                "upper_chunk": args.upper_chunk,
            },
            "targets": reports,
            "launch": (
                "retail boot establishes and relocks the baseline registers; "
                "the harness then configures RAM protection and injects guarded "
                "source and target bytes"
            ),
            "evidence_scope": (
                "pinned Wabbitemu emulator-core behavior and TilEm source "
                "predictions; not an OS/UI launch or physical ASIC behavior"
            ),
        }
        manifest = args.output_dir / "manifest.json"
        manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError, WabbitemuHeadlessError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(result, indent=2))
        return
    for item in reports:
        native = item["native"]
        comparison = "agree" if item["predicates_agree"] else "differs from TilEm"
        print(
            f"mode {item['mode']} page {item['selector']:02X} "
            f"offset {item['page_offset']:04X}: {native['classification']} "
            f"({comparison})"
        )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
