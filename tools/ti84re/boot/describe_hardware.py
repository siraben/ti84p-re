#!/usr/bin/env python3
"""Describe and verify the TI-84 Plus retail boot hardware sequence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ti84re.boot.hardware import (
    BOOT_PORT_WRITES,
    analyze_boot_trace,
    dataclass_dict,
    first_ram_test_mismatch,
    protected_flash_gate_writes,
    ram_test_pattern,
    reset_delay,
    validate_boot_port_writes,
)
from ti84re.boot.lcd_diagnostic import lcd_diagnostic_summary
from ti84re.trace.hardware import iter_resolved_executions
from ti84re.rom.image import RomImage
from ti84re.paths import DEFAULT_ROM


def integer(value: str) -> int:
    return int(value, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--json", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("delay", help="calculate reset-delay counts and timing")
    subparsers.add_parser("manifest", help="verify and print ordered boot writes")
    subparsers.add_parser(
        "protected-writes", help="classify protected Flash-gate wrappers"
    )
    trace = subparsers.add_parser(
        "trace", help="compare a full-reset TilEm trace with the manifest"
    )
    trace.add_argument("path", type=Path)
    pattern = subparsers.add_parser("ram-pattern", help="generate the RAM-test pattern")
    pattern.add_argument("length", type=integer)
    pattern.add_argument("--check", type=Path)
    subparsers.add_parser(
        "lcd-diagnostic",
        help="decode dormant LCD patterns, contrast sweep, and keypad table",
    )
    args = parser.parse_args()

    try:
        if args.command == "delay":
            report = dataclass_dict(reset_delay())
            report["standard_seconds_at_6mhz"] = reset_delay().seconds()
            payload: object = report
        elif args.command == "manifest":
            rom = RomImage.from_path(args.rom)
            errors = validate_boot_port_writes(rom)
            payload = {
                "valid": not errors,
                "errors": list(errors),
                "writes": [dataclass_dict(item) for item in BOOT_PORT_WRITES],
            }
        elif args.command == "protected-writes":
            rom = RomImage.from_path(args.rom)
            writes = protected_flash_gate_writes(rom)
            payload = {
                "enable_count": sum(item.action == "enable" for item in writes),
                "disable_count": sum(item.action == "disable" for item in writes),
                "writes": [dataclass_dict(item) for item in writes],
            }
        elif args.command == "trace":
            analysis = analyze_boot_trace(
                iter_resolved_executions(
                    args.path,
                    initial_mapping="ti84p-reset",
                )
            )
            payload = {
                "valid": analysis.valid,
                "errors": list(analysis.errors),
                "processed_instructions": analysis.processed_instructions,
                "observed_boot_writes": analysis.observed_boot_writes,
                "reset_delay": dataclass_dict(analysis.reset_delay),
            }
        elif args.command == "ram-pattern":
            pattern_bytes = ram_test_pattern(args.length)
            checked = args.check.read_bytes() if args.check else pattern_bytes
            if len(checked) != args.length:
                parser.error("--check file length does not match LENGTH")
            payload = {
                "length": args.length,
                "period": 0xFB,
                "first_mismatch": first_ram_test_mismatch(checked),
                "hex": pattern_bytes.hex(),
            }
        else:
            payload = lcd_diagnostic_summary(RomImage.from_path(args.rom))
    except (OSError, ValueError) as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(payload, indent=2))
        return
    if args.command == "delay":
        print(
            f"{payload['outer_iterations']} outer x "
            f"{payload['inner_iterations']} inner; "
            f"{payload['total_instruction_count']} instructions"
        )
        print(
            f"standard Z80: {payload['standard_total_tstates']} T-states "
            f"({payload['standard_seconds_at_6mhz']:.6f} s at 6 MHz)"
        )
        print(
            f"pinned TilEm model: {payload['tilem_total_tstates']} T-states "
            f"({payload['tilem_difference_tstates']} fewer)"
        )
    elif args.command in {"manifest", "trace"}:
        print("valid" if payload["valid"] else "invalid")
        for error in payload["errors"]:
            print(f"error: {error}")
        if args.command == "manifest":
            for item in payload["writes"]:
                print(
                    f"{item['location']}  OUT (0x{item['port']:02X}) <- "
                    f"0x{item['value']:02X}  {item['group']}"
                )
        else:
            delay = payload["reset_delay"]
            print(
                f"processed {payload['processed_instructions']} instruction(s); "
                f"matched {payload['observed_boot_writes']} boot write(s)"
            )
            print(
                f"reset delay: {delay['total_instruction_count']} instruction(s), "
                f"{delay['elapsed_tstates']} emulator T-states"
            )
    elif args.command == "protected-writes":
        print(
            f"{payload['enable_count']} guarded enable(s), "
            f"{payload['disable_count']} checked disable(s)"
        )
        for item in payload["writes"]:
            print(f"{item['location']}  {item['action']}")
    elif args.command == "ram-pattern":
        mismatch = payload["first_mismatch"]
        print(
            f"length={payload['length']} period={payload['period']} "
            f"first_mismatch={mismatch if mismatch is not None else 'none'}"
        )
    else:
        reachability = payload["reachability"]
        print(
            f"valid={payload['valid']} reachable={reachability['reachable']} "
            f"via {reachability['branch_location']}"
        )
        print(
            f"{payload['pattern_checkpoints']} screen pattern(s), "
            f"{payload['contrast_checkpoints']} contrast step(s), "
            f"{payload['key_count']} key prompt(s)"
        )
        print(
            f"pattern writes: {payload['pattern_command_writes']} command, "
            f"{payload['pattern_data_writes']} data"
        )


if __name__ == "__main__":
    main()
