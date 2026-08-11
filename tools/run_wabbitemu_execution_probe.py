#!/usr/bin/env python3
"""Run guarded Flash execution-boundary probes under pinned Wabbitemu."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from execution_protection import (
    TI84P_BOOT_PROTECTION,
    wabbitemu_flash_execution_allowed,
)
from execution_protection_fixture import (
    PROGRAM_ORIGIN,
    assemble_probe,
    build_flash_execution_fixture,
    file_digest,
)
from wabbitemu_headless import (
    WABBITEMU_COMMIT,
    WabbitemuHeadlessError,
    run_execution_probe,
)


TOOLS = Path(__file__).resolve().parent
SOURCE = TOOLS / "emulator-probes" / "execution-protection-flash.asm"
DEFAULT_ROM = TOOLS / "rom.bin"
DEFAULT_PAGES = (0x07, 0x08, 0x09, 0x29, 0x2A)


def byte(value: str) -> int:
    parsed = int(value, 0)
    if not 0 <= parsed <= 0x3F:
        raise argparse.ArgumentTypeError("page must be between 0x00 and 0x3F")
    return parsed


def positive_count(value: str) -> int:
    count = int(value, 0)
    if count <= 0:
        raise argparse.ArgumentTypeError("count must be positive")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--page", type=byte, action="append")
    parser.add_argument("--spasm", default="spasm")
    parser.add_argument("--max-boot-steps", type=positive_count, default=5_000_000)
    parser.add_argument("--max-probe-steps", type=positive_count, default=1_000)
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
            rom_path.write_bytes(fixture.rom)
            report = run_execution_probe(
                args.binary,
                rom_path,
                machine_path,
                page,
                max_boot_steps=args.max_boot_steps,
                max_probe_steps=args.max_probe_steps,
            )
            expected = (
                "returned"
                if wabbitemu_flash_execution_allowed(
                    page,
                    TI84P_BOOT_PROTECTION.flash_lower,
                    TI84P_BOOT_PROTECTION.flash_upper,
                )
                else "violation-reset"
            )
            if report.classification != expected:
                raise WabbitemuHeadlessError(
                    f"page 0x{page:02X}: observed {report.classification}, "
                    f"expected {expected}"
                )
            if (report.call_address, report.return_address) != (
                fixture.call_address,
                fixture.return_address,
            ):
                raise WabbitemuHeadlessError(
                    f"page 0x{page:02X}: native call addresses disagree with fixture"
                )
            if report.injected_address != PROGRAM_ORIGIN or report.injected_page != 1:
                raise WabbitemuHeadlessError(
                    f"page 0x{page:02X}: native injection mapping is unexpected"
                )
            expected_registers = (
                True,
                TI84P_BOOT_PROTECTION.flash_lower,
                TI84P_BOOT_PROTECTION.flash_upper,
                TI84P_BOOT_PROTECTION.ram_lower_chunk * 0x400,
                TI84P_BOOT_PROTECTION.ram_upper_chunk * 0x400 + 0x3FF,
                TI84P_BOOT_PROTECTION.ram_mode,
            )
            observed_registers = (
                report.flash_locked,
                report.flash_lower,
                report.flash_upper,
                report.ram_lower,
                report.ram_upper,
                report.ram_mode,
            )
            if observed_registers != expected_registers:
                raise WabbitemuHeadlessError(
                    f"page 0x{page:02X}: native boot-register snapshot is unexpected"
                )
            expected_marker = page if expected == "returned" else 0xA0
            if report.marker != expected_marker:
                raise WabbitemuHeadlessError(
                    f"page 0x{page:02X}: marker is 0x{report.marker:02X}; "
                    f"expected 0x{expected_marker:02X}"
                )
            reports.append(
                {
                    "page": page,
                    "expected": expected,
                    "source_rom_sha256": fixture.source_rom_sha256,
                    "fixture_rom_sha256": fixture.fixture_rom_sha256,
                    "machine_code_sha256": fixture.machine_code_sha256,
                    "native": report.to_dict(),
                }
            )

        manifest = args.output_dir / "manifest.json"
        result = {
            "emulator": "Wabbitemu",
            "commit": WABBITEMU_COMMIT,
            "binary": str(args.binary),
            "binary_sha256": file_digest(args.binary),
            "source": str(SOURCE),
            "source_sha256": file_digest(SOURCE),
            "bounds": {
                "lower": TI84P_BOOT_PROTECTION.flash_lower,
                "upper": TI84P_BOOT_PROTECTION.flash_upper,
            },
            "pages": reports,
            "launch": (
                "retail boot establishes and relocks protection registers; "
                "the harness then injects the guarded probe into RAM page 1"
            ),
            "evidence_scope": (
                "pinned Wabbitemu emulator-core behavior; not an OS/UI launch "
                "or physical ASIC behavior"
            ),
        }
        manifest.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    except (OSError, RuntimeError, ValueError, WabbitemuHeadlessError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(result, indent=2))
        return
    for item in reports:
        native = item["native"]
        print(
            f"page {item['page']:02X}: {native['classification']} "
            f"call={native['call_visits']} target={native['target_visits']} "
            f"followup={native['target_followup_visits']} "
            f"reset={native['violation_resets']}"
        )
    print(f"manifest: {manifest}")


if __name__ == "__main__":
    main()
