#!/usr/bin/env python3
"""Compare pinned TI-84 Plus MD5-assist implementations."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys

from md5_hardware import MD5_IMPLEMENTATIONS, Md5AssistImplementation


OPERAND_NAMES = ("a", "b", "c", "d", "x", "t")
DEFAULT_OPERANDS = (
    0x67452301,
    0xEFCDAB89,
    0x98BADCFE,
    0x10325476,
    0x80636261,
    0xD76AA478,
)


def integer(value: str) -> int:
    return int(value, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        action="append",
        choices=MD5_IMPLEMENTATIONS,
        help="profile to inspect; repeat as needed (default: all)",
    )
    parser.add_argument("--mode", type=integer, default=0)
    parser.add_argument("--shift", type=integer, default=7)
    for name, default in zip(OPERAND_NAMES, DEFAULT_OPERANDS):
        parser.add_argument(f"--{name}", type=integer, default=default)
    parser.add_argument("--json", action="store_true")
    return parser


def profile_report(args: argparse.Namespace, profile_key: str) -> dict[str, object]:
    implementation = Md5AssistImplementation(profile_key)
    implementation.write_port(0x1F, args.mode)
    for port, name in zip(range(0x18, 0x1E), OPERAND_NAMES):
        implementation.load_word(port, getattr(args, name))
    implementation.write_port(0x1E, args.shift)
    profile = implementation.profile
    return {
        **asdict(profile),
        "mapped_ports": sorted(profile.mapped_ports),
        "mode": implementation.mode if profile.mapped_ports else None,
        "shift": implementation.shift if profile.mapped_ports else None,
        "operands": dict(zip(OPERAND_NAMES, implementation.operands))
        if profile.mapped_ports
        else None,
        "result": implementation.result(),
        "result_reads": [implementation.read_port(port) for port in range(0x1C, 0x20)],
        "ignored_write_count": len(implementation.ignored_writes),
    }


def report(args: argparse.Namespace) -> dict[str, object]:
    profiles = args.profile or list(MD5_IMPLEMENTATIONS)
    return {
        "implementations": [
            profile_report(args, profile_key) for profile_key in profiles
        ]
    }


def print_text(result: dict[str, object]) -> None:
    for implementation in result["implementations"]:
        if implementation["result"] is None:
            print(
                f"{implementation['key']} ({implementation['revision']}): "
                "ports 0x18-0x1F unmapped"
            )
            continue
        reads = " ".join(
            f"{value:02X}" for value in implementation["result_reads"]
        )
        print(
            f"{implementation['key']} ({implementation['revision']}): "
            f"mode={implementation['mode']} shift={implementation['shift']} "
            f"result=0x{implementation['result']:08X} reads={reads}"
        )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        result = report(args)
    except ValueError as error:
        parser.error(str(error))
    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
    else:
        print_text(result)


if __name__ == "__main__":
    main()
