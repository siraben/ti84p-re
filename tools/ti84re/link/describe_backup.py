#!/usr/bin/env python3
"""Inspect TI-8x backup files or reproduce the ROM's backup DATA payload."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from ti84re.link.backup_flags import audit_legacy_system_flags
from ti84re.rom.image import RomImage
from ti84re.link.backup import parse_backup_path, rom_data_payload
from ti84re.paths import DEFAULT_ROM


def integer(value: str) -> int:
    return int(value, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    file_parser = subparsers.add_parser("file", help="decode a .8xb backup file")
    file_parser.add_argument("path", type=Path)
    file_parser.add_argument("--json", action="store_true")

    payload_parser = subparsers.add_parser(
        "rom-payload", help="transform a source buffer as the page-3C sender does"
    )
    payload_parser.add_argument("path", type=Path)
    payload_parser.add_argument("--state", type=integer, default=0x08)
    payload_parser.add_argument("--var-class", type=integer, default=0x0A)
    payload_parser.add_argument("--output", type=Path)
    payload_parser.add_argument("--json", action="store_true")

    flags_parser = subparsers.add_parser(
        "legacy-flags",
        help="audit the fixed system-flags word against indexed ROM uses",
    )
    flags_parser.add_argument(
        "--rom",
        type=Path,
        default=DEFAULT_ROM,
    )
    flags_parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.command == "file":
        backup = parse_backup_path(args.path)
        report = backup.as_dict()
        if args.json:
            print(json.dumps(report, indent=2))
            return
        print(
            f"{report['signature']} type=0x{report['type_id']:02X} "
            f"version=0x{report['version']:02X} header={report['header_size']}"
        )
        length_status = "valid" if report["data_region_length_valid"] else "INVALID"
        print(
            f"data region: stored=0x{report['data_region_length']:04X} "
            f"expected=0x{report['expected_data_region_length']:04X} "
            f"({length_status})"
        )
        for index, (length, prefix) in enumerate(
            zip(report["section_lengths"], report["section_prefixes"], strict=True),
            start=1,
        ):
            print(f"section {index}: length=0x{length:04X} prefix={prefix}")
        status = "valid" if report["checksum_valid"] else "INVALID"
        print(
            f"checksum: stored=0x{report['stored_checksum']:04X} "
            f"computed=0x{report['computed_checksum']:04X} ({status})"
        )
        return

    if args.command == "legacy-flags":
        rom = RomImage.from_path(args.rom)
        rows = audit_legacy_system_flags(rom)
        report = {
            "rom_sha256": hashlib.sha256(rom.data).hexdigest(),
            "normalized_word": 0x0063,
            "normalized_bytes": "6300",
            "bits": [row.as_dict() for row in rows],
        }
        if args.json:
            print(json.dumps(report, indent=2))
            return
        print(
            f"ROM SHA-256 {report['rom_sha256']}\n"
            f"normalized word=0x{report['normalized_word']:04X} "
            f"bytes={report['normalized_bytes']}"
        )
        for row in rows:
            symbol = row.public_symbol or "-"
            print(
                f"+0x{row.byte_offset:02X} bit {row.bit}: "
                f"value={row.normalized_value} symbol={symbol:<11} "
                f"BIT={row.bit_tests} RES={row.resets} SET={row.sets}"
            )
        return

    result = rom_data_payload(
        args.path.read_bytes(),
        snd_rec_state=args.state,
        var_class=args.var_class,
    )
    if args.output:
        args.output.write_bytes(result.payload)
    report = result.as_dict()
    if args.json:
        print(json.dumps(report, indent=2))
        return
    print(
        f"source=0x{result.source_length:X} payload=0x{result.length:X} "
        f"prefix={result.payload[:2].hex()} checksum=0x{result.checksum:04X} "
        f"normalized_system_flags={result.normalized_system_flags}"
    )


if __name__ == "__main__":
    main()
