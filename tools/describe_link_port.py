#!/usr/bin/env python3
"""Decode TI two-wire link states or describe a raw byte handshake."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from link_port import (
    LINK_EMULATOR_PROFILE_KEYS,
    LINK_PORT_PROFILES,
    KeyboardFrame,
    KeyboardGetKeyObservation,
    analyze_keyboard_rom,
    assemble_observed_byte,
    abort_pulse_report,
    byte_report,
    classify_keyboard_getkey,
    decode_ti_keyboard_frame,
    drive_mask,
    emulator_write_sequence,
    link_port_profile,
    observed_state_to_bit,
    physical_high_mask,
    port_read_value,
)
from rom_image import RomImage


TOOLS = Path(__file__).resolve().parent


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

    commands.add_parser("profiles", help="compare pinned raw-link coverage")

    emulator = commands.add_parser("emulator", help="apply writes to one profile")
    emulator.add_argument("profile", choices=LINK_PORT_PROFILES)
    emulator.add_argument("values", nargs="+", type=unsigned_byte)
    emulator.add_argument("--peer", type=mask, default=0)

    compare = commands.add_parser("compare", help="apply writes to all emulators")
    compare.add_argument("values", nargs="+", type=unsigned_byte)
    compare.add_argument("--peer", type=mask, default=0)

    drive = commands.add_parser("drive", help="decode a port-0 write")
    drive.add_argument("value", type=unsigned_byte)

    wire = commands.add_parser("wire", help="resolve two endpoint drive masks")
    wire.add_argument("--local", type=mask, required=True)
    wire.add_argument("--peer", type=mask, required=True)

    byte_command = commands.add_parser("byte", help="describe eight bit handshakes")
    byte_command.add_argument("value", type=unsigned_byte)

    receive = commands.add_parser("receive", help="assemble eight observed states")
    receive.add_argument("states", nargs=8, type=mask)

    abort = commands.add_parser(
        "abort-pulse",
        help="count the raw both-low abort delay loop",
    )
    abort.add_argument("--cpu-hz", type=integer, default=6_000_000)
    abort.add_argument(
        "--opcode-wait",
        type=integer,
        default=1,
        help="T-states added to each Flash opcode fetch (default: OS mode 0 = 1)",
    )

    keyboard = commands.add_parser(
        "keyboard",
        help="decode the logical TI-Keyboard frame consumed by _KeyboardGetKey",
    )
    keyboard.add_argument("--no-activity", action="store_true")
    keyboard.add_argument("--prefix", type=unsigned_byte, default=0xE0)
    keyboard.add_argument(
        "--delimiter",
        choices=("error", "ordinary", "timeout"),
        default="error",
    )
    keyboard.add_argument(
        "--delimiter-error",
        dest="delimiter",
        action="store_const",
        const="error",
        help="select the deliberate DBUS error delimiter",
    )
    keyboard.add_argument(
        "--command",
        dest="keyboard_command",
        type=unsigned_byte,
        default=0x01,
    )
    keyboard.add_argument("--data", type=unsigned_byte, default=0)

    keyboard_path = commands.add_parser(
        "keyboard-path",
        help="classify an exact OS 2.55MP _KeyboardGetKey status path",
    )
    keyboard_path.add_argument("--initial-lines", type=mask, default=3)
    keyboard_path.add_argument("--legacy", action="store_true")
    keyboard_path.add_argument("--assist-status", type=unsigned_byte, default=0x10)
    keyboard_path.add_argument("--buffered", type=unsigned_byte)
    keyboard_path.add_argument("--receive-status", type=unsigned_byte, default=0)
    keyboard_path.add_argument("--prefix", type=unsigned_byte, default=0xE0)
    keyboard_path.add_argument(
        "--delimiter",
        choices=("error", "ordinary", "timeout"),
        default="error",
    )
    keyboard_path.add_argument(
        "--command",
        dest="keyboard_command",
        type=unsigned_byte,
        default=0x01,
    )
    keyboard_path.add_argument("--data", type=unsigned_byte, default=0)
    keyboard_path.add_argument("--error-handler", action="store_true")

    keyboard_rom = commands.add_parser(
        "keyboard-rom",
        help="verify the ROM bytes underlying the TI-Keyboard model",
    )
    keyboard_rom.add_argument("--rom", type=Path, default=TOOLS / "rom.bin")
    return parser


def result(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "profiles":
        profiles = []
        for key in LINK_PORT_PROFILES:
            profile = link_port_profile(key)
            row = asdict(profile)
            row["mapped_assist_ports"] = list(profile.mapped_assist_ports)
            profiles.append(row)
        return {"profiles": profiles}
    if args.command in {"emulator", "compare"}:
        keys = (
            (args.profile,)
            if args.command == "emulator"
            else LINK_EMULATOR_PROFILE_KEYS
        )
        return {
            "implementations": [
                {
                    "profile": key,
                    "writes": [
                        item.as_dict()
                        for item in emulator_write_sequence(
                            key, args.values, peer_drive=args.peer
                        )
                    ],
                }
                for key in keys
            ]
        }
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
    if args.command == "abort-pulse":
        return abort_pulse_report(
            args.cpu_hz,
            opcode_wait_tstates=args.opcode_wait,
        )
    if args.command == "keyboard":
        frame = None if args.no_activity else KeyboardFrame(
            prefix=args.prefix,
            delimiter=args.delimiter,
            command=args.keyboard_command,
            data=args.data,
        )
        return decode_ti_keyboard_frame(frame).as_dict()
    if args.command == "keyboard-path":
        observation = KeyboardGetKeyObservation(
            initial_high_lines=args.initial_lines,
            assist_available=not args.legacy,
            assist_status=args.assist_status,
            buffered_byte=args.buffered,
            receive_status=args.receive_status,
            frame=KeyboardFrame(
                prefix=args.prefix,
                delimiter=args.delimiter,
                command=args.keyboard_command,
                data=args.data,
            ),
            error_handler_invoked=args.error_handler,
        )
        return classify_keyboard_getkey(observation).as_dict()
    if args.command == "keyboard-rom":
        return analyze_keyboard_rom(RomImage.from_path(args.rom)).as_dict()
    value = assemble_observed_byte(args.states)
    return {
        "states": args.states,
        "bits": [observed_state_to_bit(state) for state in args.states],
        "value": value,
    }


def print_text(report: dict[str, object]) -> None:
    if "bcall_table_bytes" in report:
        print(
            f"bcall=0x{report['bcall_id']:04X} "
            f"table-page=0x{report['bcall_table_page']:02X} "
            f"entry={report['bcall_table_bytes']} target={report['target']}"
        )
        for region in report["regions"]:
            print(
                f"  {region['name']}: {region['location']} "
                f"length=0x{region['length']:X} sha256={region['sha256']}"
            )
        print(f"  ROM SHA-256: {report['rom_sha256']}")
        return
    if "status_name" in report:
        print(
            f"status=0x{report['status']:02X} {report['status_name']} "
            f"({report['return_address']})"
        )
        print(f"  path: {report['path']}")
        print(f"  ROM condition: {report['condition']}")
        if report["prefix"] is not None:
            print(
                f"  frame: prefix=0x{report['prefix']:02X} "
                f"delimiter={report['delimiter']} "
                f"command=0x{report['command']:02X} "
                f"data=0x{report['data']:02X}"
            )
            print(
                f"  data byte: consumed={report['data_consumed']} "
                f"returned={report['data_returned']}"
            )
        return
    if "profiles" in report:
        for row in report["profiles"]:
            ports = " ".join(f"0x{port:02X}" for port in row["mapped_assist_ports"])
            print(f"{row['key']}: {row['name']} ({row['revision']})")
            print(f"  write model: {row['write_model']}")
            print(f"  assist ports: {ports or 'none'}")
            print(
                f"  assist: advertised={row['advertises_assist']} "
                f"operational={row['assist_operational']}"
            )
            print(f"  status: {row['driver_status']}")
            print(f"  limit: {row['known_limit']}")
        return
    if "implementations" in report:
        for index, implementation in enumerate(report["implementations"]):
            if index:
                print()
            print(f"{implementation['profile']}:")
            for row in implementation["writes"]:
                print(
                    f"  write=0x{row['write_value']:02X} "
                    f"state=0x{row['state_before']:02X}->0x{row['state_after']:02X} "
                    f"latch=0b{row['local_latch']:02b} "
                    f"connector-drive=0b{row['connector_drive']:02b} "
                    f"read=0x{row['port_read']:02X}"
                )
        return
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
    if "delay_tstates" in report:
        print(
            f"{report['routine']}: base={report['base_tstates']}T + "
            f"{report['opcode_fetches']} opcode fetches * "
            f"{report['opcode_wait_tstates_per_fetch']}T = "
            f"{report['delay_tstates']} T-states at "
            f"{report['cpu_hz']} Hz = {report['nominal_seconds']:.9f} s"
        )
        print(f"  {report['scope']}")
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
