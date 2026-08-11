#!/usr/bin/env python3
"""Decode TI two-wire link states or describe a raw byte handshake."""

from __future__ import annotations

import argparse
import json
import sys

from link_port import (
    assemble_observed_byte,
    byte_report,
    drive_mask,
    observed_state_to_bit,
    physical_high_mask,
    port_read_value,
)


def integer(value: str) -> int:
    return int(value, 0)


def mask(value: str) -> int:
    parsed = integer(value)
    if not 0 <= parsed <= 3:
        raise argparse.ArgumentTypeError("line mask must be between 0 and 3")
    return parsed


def unsigned_byte(value: str) -> int:
    parsed = integer(value)
    if not 0 <= parsed <= 0xFF:
        raise argparse.ArgumentTypeError("value must be between 0 and 255")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    commands = parser.add_subparsers(dest="command", required=True)

    drive = commands.add_parser("drive", help="decode a port-0 write")
    drive.add_argument("value", type=unsigned_byte)

    wire = commands.add_parser("wire", help="resolve two endpoint drive masks")
    wire.add_argument("--local", type=mask, required=True)
    wire.add_argument("--peer", type=mask, required=True)

    byte_command = commands.add_parser("byte", help="describe eight bit handshakes")
    byte_command.add_argument("value", type=unsigned_byte)

    receive = commands.add_parser("receive", help="assemble eight observed states")
    receive.add_argument("states", nargs=8, type=mask)
    return parser


def result(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "drive":
        drive = drive_mask(args.value)
        return {
            "write_value": args.value,
            "drive_mask": drive,
            "high_lines_without_peer": physical_high_mask(drive),
        }
    if args.command == "wire":
        return {
            "local_drive": args.local,
            "peer_drive": args.peer,
            "high_lines": physical_high_mask(args.local, args.peer),
            "port_read": port_read_value(args.local, args.peer),
        }
    if args.command == "byte":
        return byte_report(args.value)
    value = assemble_observed_byte(args.states)
    return {
        "states": args.states,
        "bits": [observed_state_to_bit(state) for state in args.states],
        "value": value,
    }


def print_text(report: dict[str, object]) -> None:
    if "write_value" in report:
        print(
            f"write=0x{report['write_value']:02X} drive=0b{report['drive_mask']:02b} "
            f"unopposed-high=0b{report['high_lines_without_peer']:02b}"
        )
        return
    if "port_read" in report:
        print(
            f"local-drive=0b{report['local_drive']:02b} "
            f"peer-drive=0b{report['peer_drive']:02b} "
            f"high-lines=0b{report['high_lines']:02b} "
            f"port-read=0x{report['port_read']:02X}"
        )
        return
    if "bit_order" in report:
        print(f"byte=0x{report['value']:02X} ({report['bit_order']})")
        for item in report["bits"]:
            print(
                f"bit {item['index']}: {item['bit']} "
                f"drive=0b{item['sender_drive']:02b} "
                f"receiver-sees=0b{item['initial_high_lines']:02b}"
            )
            for phase in item["phases"]:
                print(
                    f"  {phase['name']:<20} "
                    f"sender=0b{phase['sender_drive']:02b} "
                    f"receiver=0b{phase['receiver_drive']:02b} "
                    f"high=0b{phase['high_lines']:02b}"
                )
        return
    states = " ".join(f"0b{state:02b}" for state in report["states"])
    bits = "".join(str(bit) for bit in report["bits"])
    print(f"states={states} lsb-first-bits={bits} byte=0x{report['value']:02X}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        report = result(args)
    except ValueError as error:
        parser.error(str(error))
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print_text(report)


if __name__ == "__main__":
    main()
