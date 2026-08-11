#!/usr/bin/env python3
"""Decode TI-84 Plus ASIC status, identity, protection, and GPIO operations."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from asic_control import (
    ASIC_IDENTITIES,
    ASIC_IMPLEMENTATIONS,
    REVIEWED_ASIC_IO_DATA,
    audit_immediate_io,
    decode_battery_configuration,
    decode_port02,
    decode_port15,
    decode_port21,
    iter_gpio_read_modify_writes,
    iter_immediate_port_consumers,
    iter_port02_consumers,
    raw_port02_read_locations,
    summarize_immediate_port_consumers,
    summarize_port02_consumers,
)
from rom_image import RomImage
from z80_disassembly import DisassemblyError, disassemble_page

TOOLS = Path(__file__).resolve().parent


def integer(value: str) -> int:
    return int(value, 0)


def consumer_payload(consumer) -> dict:
    """Serialize one conservative immediate-port consumer."""

    return {
        "location": str(consumer.read.location),
        "read": consumer.read.text,
        "test_location": (
            None if consumer.test is None else str(consumer.test.location)
        ),
        "test": None if consumer.test is None else consumer.test.text,
        "form": consumer.form,
        "mask": consumer.mask,
        "bits": list(consumer.bits),
        "intervening": [
            instruction.text for instruction in consumer.intervening
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="append", type=integer, default=[])
    parser.add_argument("--identity", action="append", type=integer, default=[])
    parser.add_argument("--port21", action="append", type=integer, default=[])
    parser.add_argument("--battery-config", action="append", type=integer, default=[])
    parser.add_argument(
        "--scan-gpio",
        action="store_true",
        help="scan ROM pages for adjacent GPIO read-modify-write sequences",
    )
    parser.add_argument(
        "--scan-status-consumers",
        action="store_true",
        help="classify direct port-0x02 reads by their nearby A test",
    )
    parser.add_argument(
        "--scan-port21-consumers",
        action="store_true",
        help="classify direct port-0x21 reads by their nearby A test",
    )
    parser.add_argument(
        "--audit-port",
        action="append",
        type=integer,
        default=[],
        help="reconcile raw and linearly decoded immediate I/O for one port",
    )
    parser.add_argument("--rom", type=Path, default=TOOLS / "rom.bin")
    parser.add_argument("--page", action="append", type=integer)
    parser.add_argument("--z80dasm", default="z80dasm", help="z80dasm executable")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--implementations",
        action="store_true",
        help="compare pinned emulator coverage for these ASIC-control ports",
    )
    args = parser.parse_args()

    if not any(
        (
            args.status,
            args.identity,
            args.port21,
            args.battery_config,
            args.scan_gpio,
            args.scan_status_consumers,
            args.scan_port21_consumers,
            args.audit_port,
            args.implementations,
        )
    ):
        args.status = [0xE3]
        args.identity = sorted(ASIC_IDENTITIES)
        args.port21 = [0]
        args.battery_config = [0x06, 0x46, 0x86, 0xC6]

    try:
        statuses = [asdict(decode_port02(value)) for value in args.status]
        identities = []
        for value in args.identity:
            identity = decode_port15(value)
            identities.append(
                asdict(identity) if identity is not None else {"value": value, "known": False}
            )
        controls = [asdict(decode_port21(value)) for value in args.port21]
        battery = [
            asdict(decode_battery_configuration(value))
            for value in args.battery_config
        ]
    except ValueError as error:
        parser.error(str(error))

    gpio = []
    status_consumers = []
    status_consumer_objects = []
    port21_consumers = []
    port21_consumer_objects = []
    status_coverage = {}
    all_instructions = []
    if (
        args.scan_gpio
        or args.scan_status_consumers
        or args.scan_port21_consumers
        or args.audit_port
    ):
        rom = RomImage.from_path(args.rom)
        pages = tuple(args.page if args.page is not None else range(rom.page_count))
        try:
            for page in pages:
                if not 0 <= page < rom.page_count:
                    parser.error(f"page 0x{page:X} is outside this ROM")
                instructions = disassemble_page(rom, page, executable=args.z80dasm)
                all_instructions.extend(instructions)
                if args.scan_gpio:
                    for operation in iter_gpio_read_modify_writes(instructions):
                        gpio.append(
                            {
                                "location": str(operation.read.location),
                                "port": operation.port,
                                "operation": operation.operation,
                                "mask": operation.mask,
                                "instructions": [
                                    operation.read.text,
                                    operation.modify.text,
                                    operation.write.text,
                                ],
                            }
                        )
                if args.scan_status_consumers:
                    for consumer in iter_port02_consumers(instructions):
                        status_consumer_objects.append(consumer)
                        status_consumers.append(consumer_payload(consumer))
                if args.scan_port21_consumers:
                    for consumer in iter_immediate_port_consumers(instructions, 0x21):
                        port21_consumer_objects.append(consumer)
                        port21_consumers.append(consumer_payload(consumer))
        except DisassemblyError as error:
            parser.exit(2, f"{parser.prog}: {error}\n")

    status_summary = summarize_port02_consumers(status_consumer_objects)
    port21_summary = summarize_immediate_port_consumers(port21_consumer_objects)
    if args.scan_status_consumers:
        raw_locations = raw_port02_read_locations(rom, pages)
        decoded_locations = {consumer.read.location for consumer in status_consumer_objects}
        raw_location_set = set(raw_locations)
        status_coverage = {
            "raw_opcode_count": len(raw_locations),
            "decoded_consumer_count": len(status_consumer_objects),
            "unclassified_count": status_summary.get(None, 0),
            "raw_without_decoded_consumer": [
                str(location)
                for location in raw_locations
                if location not in decoded_locations
            ],
            "decoded_without_raw_opcode": [
                str(location)
                for location in sorted(
                    decoded_locations - raw_location_set,
                    key=lambda location: (location.page, location.address),
                )
            ],
            "complete": (
                raw_location_set == decoded_locations
                and status_summary.get(None, 0) == 0
            ),
        }

    def audit_payload(port: int, directions: tuple[str, ...]) -> dict:
        audit = audit_immediate_io(
            rom,
            all_instructions,
            (port,),
            pages,
            directions=directions,
            reviewed_data=REVIEWED_ASIC_IO_DATA,
        )
        direction_counts = {}
        for direction in directions:
            selected = [
                item
                for item in audit.classifications
                if item.candidate.direction == direction
            ]
            direction_counts[direction] = {
                "raw": len(selected),
                "instruction": sum(
                    item.classification == "instruction" for item in selected
                ),
                "operand_overlap": sum(
                    item.classification == "operand-overlap" for item in selected
                ),
                "reviewed_data": sum(
                    item.classification == "reviewed-data" for item in selected
                ),
                "unclassified": sum(
                    item.classification == "unclassified" for item in selected
                ),
            }
        return {
            "port": port,
            "directions": direction_counts,
            "classification_counts": audit.classification_counts,
            "raw_candidates": [
                {
                    "location": str(item.candidate.location),
                    "direction": item.candidate.direction,
                    "classification": item.classification,
                    "owner_location": (
                        None
                        if item.instruction is None
                        else str(item.instruction.location)
                    ),
                    "owner": (
                        None if item.instruction is None else item.instruction.text
                    ),
                    "note": item.note,
                }
                for item in audit.classifications
            ],
            "decoded_without_raw": [
                {
                    "location": str(instruction.location),
                    "instruction": instruction.text,
                }
                for instruction in audit.decoded_without_raw
            ],
            "complete": audit.complete,
        }

    audits = {}
    if args.scan_status_consumers:
        audits[0x02] = audit_payload(0x02, ("in",))
    if args.scan_port21_consumers:
        audits[0x21] = audit_payload(0x21, ("in", "out"))
    if args.scan_gpio:
        for port in (0x39, 0x3A):
            audits[port] = audit_payload(port, ("in", "out"))
    for port in args.audit_port:
        if not 0 <= port <= 0xFF:
            parser.error(f"port 0x{port:X} is outside 0x00-0xFF")
        audits[port] = audit_payload(port, ("in", "out"))

    result = {
        "port02_status": statuses,
        "port15_identity": identities,
        "port21_control": controls,
        "battery_configuration": battery,
        "gpio_read_modify_write": gpio,
        "port02_consumers": status_consumers,
        "port02_consumer_summary": {
            "unclassified" if mask is None else f"0x{mask:02X}": count
            for mask, count in sorted(
                status_summary.items(),
                key=lambda item: -1 if item[0] is None else item[0],
            )
        },
        "port02_consumer_coverage": status_coverage,
        "port21_consumers": port21_consumers,
        "port21_consumer_summary": {
            "unclassified" if mask is None else f"0x{mask:02X}": count
            for mask, count in sorted(
                port21_summary.items(),
                key=lambda item: -1 if item[0] is None else item[0],
            )
        },
        "immediate_io_audits": {
            f"0x{port:02X}": payload for port, payload in sorted(audits.items())
        },
        "implementations": [
            {
                **asdict(profile),
                "mapped_ports": sorted(profile.mapped_ports),
            }
            for profile in ASIC_IMPLEMENTATIONS.values()
        ]
        if args.implementations
        else [],
    }
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
        return

    for status in statuses:
        active = [name for name, value in status.items() if name != "raw" and value]
        print(f"port02 0x{status['raw']:02X}: {','.join(active) or 'none'}")
    for identity in identities:
        if identity.get("known") is False:
            print(f"port15 0x{identity['value']:02X}: unknown public identity")
        else:
            location = (
                f" ({identity['ram_location']})"
                if identity["ram_location"] is not None
                else ""
            )
            print(
                f"port15 0x{identity['value']:02X}: {identity['reference']} "
                f"USB={identity['usb_driver']} RAM={identity['ram_kib']}KiB"
                f"{location}"
            )
    for control in controls:
        print(
            f"port21 0x{control['raw']:02X}: visible=0x{control['visible_value']:02X} "
            f"flash-group={control['flash_group']} "
            f"RAM-mode={control['ram_execution_mode']} "
            f"TilEm-mask=0x{control['tilem_ram_address_mask']:X}"
        )
    for config in battery:
        print(
            f"port04 0x{config['raw']:02X}: selector={config['selector']} "
            f"TilEm-threshold={config['tilem_threshold_tenths_volt'] / 10:.1f}V"
        )
    for operation in gpio:
        print(
            f"{operation['location']} port 0x{operation['port']:02X} "
            f"{operation['operation']} 0x{operation['mask']:02X}"
        )
    for mask, count in result["port02_consumer_summary"].items():
        print(f"port02 consumer {mask}: {count}")
    for mask, count in result["port21_consumer_summary"].items():
        print(f"port21 consumer {mask}: {count}")
    if status_coverage:
        print(
            "port02 coverage: "
            f"raw={status_coverage['raw_opcode_count']} "
            f"decoded={status_coverage['decoded_consumer_count']} "
            f"unclassified={status_coverage['unclassified_count']} "
            f"complete={str(status_coverage['complete']).lower()}"
        )
    for port, audit in sorted(audits.items()):
        fields = []
        for direction, counts in audit["directions"].items():
            fields.append(
                f"{direction}:raw={counts['raw']},code={counts['instruction']},"
                f"overlap={counts['operand_overlap']},data={counts['reviewed_data']},"
                f"unknown={counts['unclassified']}"
            )
        print(
            f"port 0x{port:02X} audit: {'; '.join(fields)}; "
            f"complete={str(audit['complete']).lower()}"
        )
    for profile in result["implementations"]:
        ports = ",".join(f"0x{port:02X}" for port in profile["mapped_ports"])
        identity = (
            "model-dependent"
            if profile["fixed_port15"] is None
            else f"0x{profile['fixed_port15']:02X}"
        )
        print(
            f"{profile['key']} ({profile['revision']}): ports={ports} "
            f"port15={identity}; port21={profile['port21_read_policy']}; "
            f"GPIO={profile['gpio_policy']}"
        )


if __name__ == "__main__":
    main()
