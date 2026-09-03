#!/usr/bin/env python3
"""Decode TI-84 Plus bus waits for all CPU-speed selector values."""

from __future__ import annotations

import argparse
import json
import sys

from ti84re.hardware.bus_timing import (
    EMULATOR_PROFILE_KEYS,
    TIMING_PORTS,
    TIMING_PROFILES,
    TimingImplementation,
)


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=TIMING_PROFILES,
        default="documented",
        help="implementation profile (default: documented)",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="compare the three pinned emulator profiles",
    )
    parser.add_argument(
        "--extra-speeds",
        action="store_true",
        help="enable Wabbitemu's externally configured 20/25 MHz modes",
    )
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
    return parser


def implementation_report(
    implementation: TimingImplementation,
) -> dict[str, object]:
    profile = implementation.profile
    return {
        "profile": profile.key,
        "implementation": profile.name,
        "revision": profile.revision,
        "mapped_ports": sorted(profile.mapped_ports),
        "speed_policy": profile.speed_policy,
        "delay_registers": profile.delay_registers,
        "lcd_ready_policy": profile.lcd_ready_policy,
        "timer_prescaler": profile.timer_prescaler,
        "driver_status": profile.driver_status,
        "known_limit": profile.known_limit,
        "extra_speeds": implementation.extra_speeds,
        "port20_stored": implementation.port20,
        "port20_readback": implementation.read_port(0x20),
        "current_speed_mode": implementation.decoder.speed_mode,
        "clock_mhz": implementation.clock_mhz(),
        "selectable_speed_modes": list(implementation.selectable_speed_modes()),
        "port2e": implementation.read_port(0x2E),
        "port2f": implementation.read_port(0x2F),
        "accepted_writes": implementation.writes,
        "ignored_writes": [
            {"port": port, "value": value}
            for port, value in implementation.ignored_writes
        ],
        "modes": implementation.rows(),
    }


def report(args: argparse.Namespace) -> dict[str, object]:
    profile_keys = EMULATOR_PROFILE_KEYS if args.compare else (args.profile,)
    implementations = []
    for profile_key in profile_keys:
        if args.preset == "zero":
            implementation = TimingImplementation(
                profile=profile_key, extra_speeds=args.extra_speeds
            )
        else:
            implementation = TimingImplementation.ti84p_os(
                profile_key, extra_speeds=args.extra_speeds
            )
        for port, value in args.write:
            implementation.write_port(port, value)
        implementations.append(implementation_report(implementation))
    return {"implementations": implementations}


def print_text(result: dict[str, object]) -> None:
    for index, implementation in enumerate(result["implementations"]):
        if index:
            print()
        print(
            f"{implementation['profile']} ({implementation['revision']}): "
            f"speed-mode={implementation['current_speed_mode']} "
            f"clock={implementation['clock_mhz']}MHz "
            f"port20={implementation['port20_stored']:02X}/"
            f"{implementation['port20_readback']:02X}"
        )
        if not implementation["delay_registers"]:
            print("  ports 0x29-0x2F: unmapped; no programmable bus waits")
        else:
            print(
                f"  port2e=0x{implementation['port2e']:02X} "
                f"port2f=0x{implementation['port2f']:02X}"
            )
            print(
                "  mode  port value  MHz  LCD-I/O  Flash +1T      RAM +1T        "
                "LCD-ready  doc-div"
            )
            for row in implementation["modes"]:
                waits = row["memory_waits"]
                print(
                    f"   {row['speed_mode']}    0x{row['delay_port']:02X}  "
                    f"0x{row['delay_value']:02X}   {row['clock_mhz']:>2}     "
                    f"{row['lcd_access_wait']:>2}T     "
                    f"{wait_names(waits, 'flash'):<14} "
                    f"{wait_names(waits, 'ram'):<14} "
                    f"{row['lcd_ready_hold']:>3}T       "
                    f"/{row['documented_mode3_divisor']}"
                )
        for ignored in implementation["ignored_writes"]:
            print(
                f"  ignored write: 0x{ignored['port']:02X}="
                f"0x{ignored['value']:02X}"
            )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = report(args)

    if args.json:
        json.dump(result, sys.stdout, indent=2)
        print()
        return
    print_text(result)


if __name__ == "__main__":
    main()
