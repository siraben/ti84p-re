#!/usr/bin/env python3
"""Compare timer sources, expiry policy, ROM chunks, and RTC support."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from fractions import Fraction
import json
import sys

from timer_hardware import (
    TIMER_IMPLEMENTATION_PROFILES,
    decode_timer_source,
    rom_timer_chunks,
    rom_timer_ticks,
    timer_duration,
    timer_expiry,
)


def integer(value: str) -> int:
    return int(value, 0)


def _profiles(values: list[str] | None) -> list[str]:
    return values or [profile.name for profile in TIMER_IMPLEMENTATION_PROFILES]


def _serializable(value: object) -> object:
    if isinstance(value, Fraction):
        return str(value)
    if isinstance(value, dict):
        return {key: _serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serializable(item) for item in value]
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("profiles", help="compare pinned implementation profiles")

    source = commands.add_parser("source", help="decode source-register values")
    source.add_argument("values", nargs="+", type=integer)
    source.add_argument("--profile", action="append")
    source.add_argument("--cpu-hz", type=integer, default=15_000_000)
    source.add_argument("--mode3-prescaler", type=integer, default=1)

    duration = commands.add_parser("duration", help="compute first-expiry timing")
    duration.add_argument("--source", type=integer, required=True)
    duration.add_argument("--counter", type=integer, required=True)
    duration.add_argument("--profile", action="append")
    duration.add_argument("--cpu-hz", type=integer, default=15_000_000)
    duration.add_argument("--mode3-prescaler", type=integer, default=1)

    chunks = commands.add_parser("chunks", help="decode ROM radix-255 durations")
    chunks.add_argument("durations", nargs="+", type=integer)

    expiry = commands.add_parser("expiry", help="compare one timer expiry")
    expiry.add_argument("--mode", type=integer, required=True)
    expiry.add_argument("--counter", type=integer, default=1)
    expiry.add_argument("--profile", action="append")
    expiry.add_argument("--already-completed", action="store_true")
    expiry.add_argument("--halted", action="store_true")
    expiry.add_argument("--no-standard-timer", action="store_true")

    commands.add_parser("rtc", help="compare RTC implementation policy")
    return parser


def report(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "profiles":
        return {"profiles": [asdict(profile) for profile in TIMER_IMPLEMENTATION_PROFILES]}
    if args.command == "source":
        rows = []
        for value in args.values:
            for profile in _profiles(args.profile):
                decoded = decode_timer_source(
                    profile,
                    value,
                    cpu_hz=args.cpu_hz,
                    mode3_prescaler=args.mode3_prescaler,
                )
                rows.append(
                    {"profile": profile, "value": value, "off": decoded is None}
                    if decoded is None
                    else asdict(decoded)
                )
        return {"sources": rows}
    if args.command == "duration":
        return {
            "durations": [
                asdict(
                    timer_duration(
                        profile,
                        args.source,
                        args.counter,
                        cpu_hz=args.cpu_hz,
                        mode3_prescaler=args.mode3_prescaler,
                    )
                )
                for profile in _profiles(args.profile)
            ]
        }
    if args.command == "chunks":
        return {
            "durations": [
                {
                    "encoded": duration,
                    "ticks": rom_timer_ticks(duration),
                    "chunks": list(rom_timer_chunks(duration)),
                }
                for duration in args.durations
            ]
        }
    if args.command == "expiry":
        return {
            "expiries": [
                asdict(
                    timer_expiry(
                        profile,
                        args.mode,
                        counter=args.counter,
                        already_completed=args.already_completed,
                        halted=args.halted,
                        standard_timer_enabled=not args.no_standard_timer,
                    )
                )
                for profile in _profiles(args.profile)
            ]
        }
    return {
        "rtc": [
            {
                "profile": profile.name,
                "revision": profile.revision,
                "ports_0x40_0x48": profile.rtc_ports,
                "source": profile.rtc_source,
                "disabled_read": profile.rtc_disabled_read,
            }
            for profile in TIMER_IMPLEMENTATION_PROFILES
        ]
    }


def print_text(data: dict[str, object]) -> None:
    if "profiles" in data:
        for profile in data["profiles"]:
            print(f"{profile['name']} ({profile['revision']})")
            print(f"  source: {profile['source_model']}")
            print(f"  expiry: {profile['expiry_model']}")
            print(f"  RTC: {profile['rtc_source']}")
        return
    if "sources" in data:
        for row in data["sources"]:
            if row.get("off", False):
                print(f"{row['profile']} 0x{row['value']:02X}: off")
                continue
            print(
                f"{row['profile']} 0x{row['value']:02X}: {row['family']} "
                f"source={row['source_hz']} Hz divisor={row['divisor']} "
                f"tick={float(row['tick_hz']):.9f} Hz"
            )
            print(f"  {row['note']}")
        return
    if "durations" in data and data["durations"] and "profile" in data["durations"][0]:
        for row in data["durations"]:
            if row["expires"]:
                seconds = float(row["duration_seconds"])
                print(
                    f"{row['profile']}: ticks={row['effective_counter_ticks']} "
                    f"scheduled-periods={row['scheduled_periods_to_expiry']} "
                    f"duration={seconds:.12g} s"
                )
            else:
                print(f"{row['profile']}: does not expire ({row['note']})")
        return
    if "durations" in data:
        for row in data["durations"]:
            chunks = " ".join(str(value) for value in row["chunks"]) or "none"
            print(
                f"0x{row['encoded']:04X}: ticks={row['ticks']} "
                f"counter-writes={chunks}"
            )
        return
    if "expiries" in data:
        for row in data["expiries"]:
            generated = row["interrupt_generated"]
            interrupt = "unknown" if generated is None else ("yes" if generated else "no")
            print(
                f"{row['profile']}: completion={row['completion_visible']} "
                f"status=0x{row['mode_read_after_expiry']:02X} "
                f"interrupt={interrupt} running={row['running_after_expiry']}"
            )
            print(f"  {row['note']}")
        return
    for row in data["rtc"]:
        support = "mapped" if row["ports_0x40_0x48"] else "unmapped"
        print(f"{row['profile']} ({row['revision']}): {support}")
        print(f"  source: {row['source']}")
        print(f"  disabled read: {row['disabled_read']}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        data = report(args)
    except ValueError as error:
        parser.error(str(error))
    if args.json:
        json.dump(_serializable(data), sys.stdout, indent=2)
        print()
    else:
        print_text(data)


if __name__ == "__main__":
    main()
