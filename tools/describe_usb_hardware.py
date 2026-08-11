#!/usr/bin/env python3
"""Inspect USB/FDRC registers, events, assist rates, and emulator coverage."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys

from usb_hardware import (
    USB_EMULATOR_PROFILES,
    boot_usb_event_action,
    decode_fdrc_bits,
    decode_link_assist_rate,
    decode_usb_line_state,
    emulator_initial_usb_read,
    fdrc_register,
    main_usb_event_targets,
    usb_active_low_summary_bits,
    wabbitemu_port4a_write,
)


def integer(value: str) -> int:
    return int(value, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("profiles", help="compare pinned emulator coverage")

    registers = commands.add_parser("register", help="map TI ports to FDRC names")
    registers.add_argument("ports", nargs="+", type=integer)

    bits = commands.add_parser("bits", help="decode imported FDRC bit names")
    bits.add_argument("port", type=integer)
    bits.add_argument("values", nargs="+", type=integer)

    line = commands.add_parser("line", help="decode Wabbitemu paired line states")
    line.add_argument("values", nargs="+", type=integer)

    assist = commands.add_parser("assist", help="decode link-assist rate values")
    assist.add_argument("values", nargs="+", type=integer)

    events = commands.add_parser("events", help="decode USB summary/event bytes")
    events.add_argument("values", nargs="+", type=integer)

    reads = commands.add_parser("reads", help="show pinned initial USB reads")
    reads.add_argument("ports", nargs="*", type=integer)

    port4a = commands.add_parser("wabbit-port4a", help="model Wabbitemu port 0x4A")
    port4a.add_argument("value", type=integer)
    port4a.add_argument("--line-state", type=integer, default=0xA5)
    port4a.add_argument("--events", type=integer, default=0x50)
    return parser


def report(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "profiles":
        return {"profiles": [asdict(profile) for profile in USB_EMULATOR_PROFILES]}
    if args.command == "register":
        return {
            "registers": [
                {"port": port, "mapped": register is not None}
                if (register := fdrc_register(port)) is None
                else {**asdict(register), "mapped": True}
                for port in args.ports
            ]
        }
    if args.command == "bits":
        return {
            "bits": [
                {"port": args.port, "value": value, "set_names": list(decode_fdrc_bits(args.port, value))}
                for value in args.values
            ]
        }
    if args.command == "line":
        return {"lines": [asdict(decode_usb_line_state(value)) for value in args.values]}
    if args.command == "assist":
        return {"rates": [asdict(decode_link_assist_rate(value)) for value in args.values]}
    if args.command == "events":
        return {
            "events": [
                {
                    "value": value,
                    "active_summary_bits_if_port55": list(usb_active_low_summary_bits(value)),
                    "main_targets_if_port56": list(main_usb_event_targets(value)),
                    "boot_action_if_port56": boot_usb_event_action(value),
                }
                for value in args.values
            ]
        }
    if args.command == "reads":
        ports = args.ports or sorted(
            {port for profile in USB_EMULATOR_PROFILES for port in profile.mapped_ports}
        )
        return {
            "reads": [
                {
                    "emulator": profile.name,
                    "port": port,
                    "modeled": (value := emulator_initial_usb_read(profile.name, port)) is not None,
                    "value": value,
                }
                for profile in USB_EMULATOR_PROFILES
                for port in ports
            ]
        }
    return {"result": asdict(wabbitemu_port4a_write(args.value, line_state=args.line_state, events=args.events))}


def print_text(data: dict[str, object]) -> None:
    if "profiles" in data:
        for row in data["profiles"]:
            ports = " ".join(f"0x{port:02X}" for port in row["mapped_ports"])
            print(f"{row['name']} ({row['revision']}): {ports}")
            print(f"  {row['controller_model']}")
            print(f"  limit: {row['known_limit']}")
        return
    if "registers" in data:
        for row in data["registers"]:
            if not row["mapped"]:
                print(f"0x{row['port']:02X}: outside modeled FDRC range")
            else:
                names = "/".join(row["names"])
                suffix = f" endpoint={row['endpoint']}" if row["endpoint"] is not None else ""
                print(f"0x{row['port']:02X} offset=0x{row['offset']:02X}: {names}{suffix}")
        return
    if "bits" in data:
        for row in data["bits"]:
            names = ", ".join(row["set_names"]) or "none"
            print(f"0x{row['port']:02X}=0x{row['value']:02X}: {names}")
        return
    if "lines" in data:
        for row in data["lines"]:
            print(
                f"0x{row['value']:02X}: D+={row['d_plus']} D-={row['d_minus']} "
                f"ID={row['id']} VBUS={row['vbus']}"
            )
        return
    if "rates" in data:
        for row in data["rates"]:
            divisor = "halt" if row["halted"] else f"divide-by-{row['divisor']}"
            print(f"0x{row['value']:02X}: {divisor} wait={row['inter_bit_wait']}")
        return
    if "events" in data:
        for row in data["events"]:
            targets = "; ".join(row["main_targets_if_port56"]) or "none"
            active = ",".join(str(bit) for bit in row["active_summary_bits_if_port55"]) or "none"
            print(f"0x{row['value']:02X}: port55-active={active}")
            print(f"  port56-main: {targets}")
            print(f"  port56-boot: {row['boot_action_if_port56']}")
        return
    if "reads" in data:
        for row in data["reads"]:
            value = f"0x{row['value']:02X}" if row["modeled"] else "unmodeled"
            print(f"{row['emulator']} port 0x{row['port']:02X}: {value}")
        return
    row = data["result"]
    print(
        f"stored=0x{row['stored_port4a']:02X} "
        f"line=0x{row['line_state_before']:02X}->0x{row['line_state_after']:02X} "
        f"events=0x{row['events_before']:02X}->0x{row['events_after']:02X} "
        f"interrupt={row['line_interrupt']}"
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        data = report(args)
    except ValueError as error:
        parser.error(str(error))
    if args.json:
        json.dump(data, sys.stdout, indent=2)
        print()
    else:
        print_text(data)


if __name__ == "__main__":
    main()
