#!/usr/bin/env python3
"""Decode or simulate the restoring RAM-selector alias probe."""

from __future__ import annotations

import argparse
import json

from ram_topology import (
    RAM_ALIAS_PATTERNS,
    RamTopologyObservation,
    infer_alias_groups,
    simulate_alias_writes,
)


def byte_sequence(value: str) -> bytes:
    compact = value.replace(",", "").replace(":", "").replace(" ", "")
    try:
        result = bytes.fromhex(compact)
    except ValueError as error:
        raise argparse.ArgumentTypeError("value must be a hexadecimal byte sequence") from error
    if len(result) != 6:
        raise argparse.ArgumentTypeError("value must contain exactly six bytes")
    return result


def backing_sequence(value: str) -> tuple[int, ...]:
    try:
        fields = tuple(int(field, 0) for field in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "backings must be six comma-separated integers"
        ) from error
    if len(fields) != 6:
        raise argparse.ArgumentTypeError("backings must contain six integers")
    return fields


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--observed",
        type=byte_sequence,
        help="six patterned reads as hexadecimal bytes",
    )
    source.add_argument(
        "--simulate-backings",
        type=backing_sequence,
        metavar="B0,B1,B2,B3,B4,B5",
        help="simulate six selector-to-backing identifiers",
    )
    parser.add_argument("--original", type=byte_sequence)
    parser.add_argument("--restored", type=byte_sequence)
    parser.add_argument("--json", action="store_true")
    return parser


def report(args: argparse.Namespace) -> dict[str, object]:
    observed = args.observed
    if observed is None:
        observed = simulate_alias_writes(args.simulate_backings)
    original = bytes(6) if args.original is None else args.original
    restored = original if args.restored is None else args.restored
    observation = RamTopologyObservation(
        original=original,
        observed=observed,
        restored=restored,
        alias_groups=infer_alias_groups(observed),
    )
    result = observation.to_dict()
    result["patterns"] = RAM_ALIAS_PATTERNS.hex().upper()
    result["restore_supplied"] = args.restored is not None
    if args.simulate_backings is not None:
        result["simulated_backings"] = list(args.simulate_backings)
    return result


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = report(args)
    if args.json:
        print(json.dumps(result, indent=2))
        return
    print(f"observed: {result['observed']}")
    print(f"topology: {result['topology_observation']}")
    groups = result["alias_groups"]
    print("alias groups: unclassified" if groups is None else f"alias groups: {groups}")
    if result["restore_supplied"]:
        print(f"restore matches: {str(result['restore_matches']).lower()}")


if __name__ == "__main__":
    main()
