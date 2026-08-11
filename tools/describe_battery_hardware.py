#!/usr/bin/env python3
"""Describe the ROM battery-level tree and TilEm threshold consequences."""

from __future__ import annotations

import argparse
import json

from battery_hardware import (
    SELECTORS,
    battery_level,
    battery_model_report,
    comparator_samples,
    parse_voltage_tenths,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--voltage", help="TilEm voltage in 0.1 V units")
    group.add_argument(
        "--samples",
        help="four 0/1 comparator samples in 06,46,86,C6 order",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        report = battery_model_report()
        if args.voltage is not None:
            tenths = parse_voltage_tenths(args.voltage)
            samples = comparator_samples(tenths)
            report["query"] = {
                "voltage": f"{tenths / 10:.1f}",
                "samples": {
                    f"0x{selector:02X}": samples[selector]
                    for selector in SELECTORS
                },
                "level": battery_level(samples),
            }
        elif args.samples is not None:
            if len(args.samples) != 4 or set(args.samples) - {"0", "1"}:
                raise ValueError("--samples must contain exactly four 0/1 digits")
            samples = {
                selector: digit == "1"
                for selector, digit in zip(SELECTORS, args.samples, strict=True)
            }
            report["query"] = {
                "samples": {
                    f"0x{selector:02X}": samples[selector]
                    for selector in SELECTORS
                },
                "level": battery_level(samples),
            }
    except ValueError as error:
        parser.error(str(error))

    if args.json:
        print(json.dumps(report, indent=2))
        return
    print("ROM order: " + " -> ".join(report["rom_test_order"]))
    for region in report["regions"]:
        lower = "-inf" if region["lower_volts"] is None else region["lower_volts"]
        upper = "+inf" if region["upper_volts"] is None else region["upper_volts"]
        bits = "".join("1" if value else "0" for value in region["samples"].values())
        print(f"[{lower},{upper}) V samples={bits} level={region['level']}")
    print(
        "reachable levels: "
        + ",".join(map(str, report["reachable_levels"]))
        + "; unreachable: "
        + ",".join(map(str, report["unreachable_levels"]))
    )
    if "query" in report:
        print("query: " + json.dumps(report["query"], sort_keys=True))


if __name__ == "__main__":
    main()
