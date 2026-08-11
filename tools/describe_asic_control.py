#!/usr/bin/env python3
"""Decode TI-84 Plus ASIC status, identity, protection, and GPIO operations."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from asic_control import (
    ASIC_IMPLEMENTATIONS,
    ASIC_IDENTITIES,
    decode_battery_configuration,
    decode_port02,
    decode_port15,
    decode_port21,
    iter_gpio_read_modify_writes,
)
from rom_image import RomImage
from z80_disassembly import DisassemblyError, disassemble_page


TOOLS = Path(__file__).resolve().parent


def integer(value: str) -> int:
    return int(value, 0)


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
    if args.scan_gpio:
        rom = RomImage.from_path(args.rom)
        pages = args.page if args.page is not None else range(rom.page_count)
        try:
            for page in pages:
                if not 0 <= page < rom.page_count:
                    parser.error(f"page 0x{page:X} is outside this ROM")
                instructions = disassemble_page(rom, page, executable=args.z80dasm)
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
        except DisassemblyError as error:
            parser.exit(2, f"{parser.prog}: {error}\n")

    result = {
        "port02_status": statuses,
        "port15_identity": identities,
        "port21_control": controls,
        "battery_configuration": battery,
        "gpio_read_modify_write": gpio,
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
