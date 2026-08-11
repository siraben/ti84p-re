#!/usr/bin/env python3
"""Decode TI-84 Plus bus waits for all CPU-speed selector values."""

from __future__ import annotations

import argparse
import json
import sys

from bus_timing import BusTiming, TIMING_PORTS


def port_write(value: str) -> tuple[int, int]:
    try:
        port_text, byte_text = value.split("=", 1)
        port, byte = int(port_text, 0), int(byte_text, 0)
    except ValueError:
        raise argparse.ArgumentTypeError("write must have the form PORT=VALUE") from None
    if port not in TIMING_PORTS:
        raise argparse.ArgumentTypeError(f"0x{port:02X} is not a timing port")
    if not 0 <= byte <= 0xFF:
        raise argparse.ArgumentTypeError("write value must be a byte")
    return port, byte


def wait_names(waits: dict[str, int], prefix: str) -> str:
    labels = {
        "opcode": "M1",
        "read": "read",
        "write": "write",
    }
    active = [
        labels[name]
        for name in labels
        if waits[f"{prefix}_{name}"]
    ]
    return ",".join(active) if active else "none"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--preset",
        choices=("zero", "ti84p-os"),
        default="ti84p-os",
        help="initial register values (default: ti84p-os)",
    )
    parser.add_argument(
        "--write",
        action="append",
        type=port_write,
        default=[],
        metavar="PORT=VALUE",
        help="apply a timing-register write; repeat as needed",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    timing = BusTiming() if args.preset == "zero" else BusTiming.ti84p_os()
    for port, value in args.write:
        timing.write_port(port, value)
    result = {
        "current_speed_mode": timing.speed_mode,
        "port2e": timing.port2e,
        "port2f": timing.port2f,
        "modes": timing.rows(),
    }

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
        return

    print(
        f"current_speed_mode={timing.speed_mode} "
        f"port2e=0x{timing.port2e:02X} port2f=0x{timing.port2f:02X}"
    )
    print(
        "mode  port value  LCD-I/O  Flash +1T      RAM +1T        "
        "LCD-ready  timer-div"
    )
    for row in result["modes"]:
        waits = row["memory_waits"]
        print(
            f" {row['speed_mode']}    0x{row['delay_port']:02X}  "
            f"0x{row['delay_value']:02X}    {row['lcd_access_wait']:>2}T     "
            f"{wait_names(waits, 'flash'):<14} "
            f"{wait_names(waits, 'ram'):<14} "
            f"{row['lcd_ready_hold']:>3}T       "
            f"/{row['documented_mode3_divisor']}"
        )


if __name__ == "__main__":
    main()
