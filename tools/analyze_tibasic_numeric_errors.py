#!/usr/bin/env python3
"""Reduce natural TI-BASIC error traces to their originating numeric guards.

The shared error shims identify an OS error code, not its cause.  This reducer
checks an ordered guard-to-shim path for each selected natural program and
stores only compact provenance, register snapshots, and trace digests.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterator, Sequence

from analyze_tibasic_coverage import digest, parse_trace
from hardware_trace import make_banker
from rom_calls import analyze_calls
from rom_image import RomImage
from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from tilem_trace_resolve import (
    IDX_AF,
    IDX_BC,
    IDX_DE,
    IDX_HL,
    IDX_SP,
    iter_records,
    read_header,
    resolve_instruction,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "tools" / "rom.bin"
DEFAULT_OUTPUT = ROOT / "tools" / "tibasic-numeric-errors.json"


SHIMS = {
    0x26E8: ("OVERFLOW", 0x81),
    0x26EC: ("DIVIDE BY 0", 0x82),
    0x26F0: ("SINGULAR MAT", 0x83),
    0x26F4: ("DOMAIN", 0x84),
    0x26F8: ("INCREMENT", 0x85),
    0x26FC: ("NONREAL ANSWERS", 0x87),
}


@dataclass(frozen=True)
class ErrorExample:
    source: str
    error: str
    error_code: int
    predicate: str
    path: tuple[tuple[str, int], ...]


EXAMPLES = {
    "divzero": ErrorExample(
        "Disp 1/0",
        "DIVIDE BY 0",
        0x82,
        "the divisor in OP1 is zero",
        (("ram", 0x2548), ("ram", 0x254B), ("ram", 0x26EC)),
    ),
    "overflow": ErrorExample(
        "Disp 10^100",
        "OVERFLOW",
        0x81,
        "the positive 10^x argument is at least 100",
        (
            ("page_02", 0x7076),
            ("page_02", 0x7078),
            ("page_02", 0x7053),
            ("page_02", 0x7056),
            ("page_02", 0x7059),
            ("ram", 0x26E8),
        ),
    ),
    "muloverflow": ErrorExample(
        "Disp 1E99*1E99",
        "OVERFLOW",
        0x81,
        "the adjusted sum of the two biased decimal exponents exceeds the representable range",
        (
            ("ram", 0x2513),
            ("ram", 0x2516),
            ("ram", 0x2517),
            ("ram", 0x2519),
            ("ram", 0x251B),
            ("ram", 0x251D),
            ("ram", 0x26E8),
        ),
    ),
    "lndomain": ErrorExample(
        "Disp ln(0)",
        "DOMAIN",
        0x84,
        "the logarithm operand in OP1 is zero",
        (
            ("page_02", 0x6F1E),
            ("ram", 0x212D),
            ("ram", 0x1DE9),
            ("ram", 0x2130),
            ("ram", 0x2131),
            ("ram", 0x211D),
            ("ram", 0x26F4),
        ),
    ),
    "increment": ErrorExample(
        "For(I,1,3,0):End",
        "INCREMENT",
        0x85,
        "the For( step value in OP1 is zero",
        (
            ("page_37", 0x4268),
            ("ram", 0x1DE9),
            ("page_37", 0x426B),
            ("ram", 0x26F8),
        ),
    ),
    "asindomain": ErrorExample(
        "Disp sin^-1(2)",
        "DOMAIN",
        0x84,
        "the inverse-sine operand is outside [-1, 1]",
        (
            ("page_02", 0x76F1),
            ("page_02", 0x76F4),
            ("page_02", 0x76F5),
            ("ram", 0x26F4),
        ),
    ),
    "acosdomain": ErrorExample(
        "Disp cos^-1(2)",
        "DOMAIN",
        0x84,
        "the inverse-cosine operand is outside [-1, 1]",
        (
            ("page_02", 0x76DF),
            ("page_02", 0x76E2),
            ("ram", 0x26F4),
        ),
    ),
    "sqrtnonreal": ErrorExample(
        "Disp sqrt(-1)",
        "NONREAL ANSWERS",
        0x87,
        "a complex result reaches the real-mode result guard",
        (
            ("ram", 0x1B8F),
            ("ram", 0x1B93),
            ("ram", 0x26FC),
        ),
    ),
    "singular": ErrorExample(
        "Disp [[1,2][2,4]]^-1",
        "SINGULAR MAT",
        0x83,
        "the pivot helper returns carry while saved bit 6 is clear",
        (
            ("page_02", 0x439C),
            ("page_02", 0x439F),
            ("page_02", 0x43A1),
            ("page_02", 0x43A2),
            ("page_02", 0x43A3),
            ("page_02", 0x43A5),
            ("ram", 0x26F0),
        ),
    ),
    "lateincrement": ErrorExample(
        "For(I,1E99,1E99):End",
        "INCREMENT",
        0x85,
        "adding the default step does not change the loop variable",
        (
            ("page_38", 0x586D),
            ("page_38", 0x5870),
            ("page_38", 0x5873),
            ("page_38", 0x5876),
            ("ram", 0x26F8),
        ),
    ),
    "negfactdomain": ErrorExample(
        "Disp (-1)!",
        "DOMAIN",
        0x84,
        "the factorial operand fails the nonnegative-integer check",
        (
            ("page_35", 0x79CF),
            ("page_35", 0x79D2),
            ("ram", 0x26F4),
        ),
    ),
    "ncrdomain": ErrorExample(
        "Disp (-1) nCr 1",
        "DOMAIN",
        0x84,
        "the left combination operand fails the positive-value check",
        (
            ("page_02", 0x4FC8),
            ("page_02", 0x4FA1),
            ("ram", 0x2125),
            ("ram", 0x1DFD),
            ("ram", 0x1E00),
            ("ram", 0x1E02),
            ("ram", 0x2128),
            ("ram", 0x211C),
            ("ram", 0x211D),
            ("ram", 0x26F4),
        ),
    ),
}


def caller_inventory(rom: RomImage) -> dict[str, object]:
    """Enumerate direct ROM references to the six numeric error shims."""

    reports = analyze_calls(rom, frozenset(SHIMS))
    grouped: dict[int, list[str]] = {address: [] for address in SHIMS}
    for report in reports:
        address = int(str(report["resolved_target"]).split(":", 1)[1], 16)
        grouped[address].append(str(report["location"]))
    return {
        "method": "direct CALL/JP operands in whole-ROM linear disassembly",
        "limitation": (
            "indirect transfers and helpers that load an error code before the "
            "common error path are not included; decoded data can produce "
            "candidates until CFG reachability is proved"
        ),
        "candidate_count": len(reports),
        "shims": [
            {
                "entry": f"00:{address:04X}",
                "error": error,
                "error_code": f"{code:02X}",
                "candidate_count": len(grouped[address]),
                "candidates": sorted(grouped[address]),
            }
            for address, (error, code) in SHIMS.items()
        ],
    }


def format_point(point: tuple[str, int]) -> str:
    space, address = point
    page = 0 if space == "ram" else int(space.removeprefix("page_"), 16)
    return f"{page:02X}:{address:04X}"


def snapshot(fields: tuple[int, ...]) -> dict[str, str]:
    af = fields[IDX_AF]
    return {
        "A": f"{af >> 8:02X}",
        "F": f"{af & 0xFF:02X}",
        "BC": f"{fields[IDX_BC]:04X}",
        "DE": f"{fields[IDX_DE]:04X}",
        "HL": f"{fields[IDX_HL]:04X}",
        "SP": f"{fields[IDX_SP]:04X}",
    }


def analyze_trace(label: str, path: Path) -> dict[str, object]:
    example = EXAMPLES[label]
    banker = make_banker("ti84p-reset")
    next_path_index = 0
    hits: Counter[tuple[str, int]] = Counter()
    candidate_snapshots: dict[str, dict[str, str]] = {}
    completed_snapshots: dict[str, dict[str, str]] = {}
    completed_paths = 0
    instruction_count = 0
    with path.open("rb") as stream:
        read_header(stream)
        records: Iterator[tuple[int, object]] = iter_records(stream)
        for record_type, payload in records:
            if record_type != 0x01:
                continue
            point = resolve_instruction(banker, payload)[0][:2]
            instruction_count += 1
            if point in example.path:
                hits[point] += 1
            if point == example.path[0]:
                candidate_snapshots = {format_point(point): snapshot(payload)}
                next_path_index = 1
            elif next_path_index and point == example.path[next_path_index]:
                candidate_snapshots[format_point(point)] = snapshot(payload)
                next_path_index += 1
                if next_path_index == len(example.path):
                    completed_snapshots = dict(candidate_snapshots)
                    completed_paths += 1
                    candidate_snapshots = {}
                    next_path_index = 0

    missing = [] if completed_paths else [
        format_point(point) for point in example.path[next_path_index:]
    ]
    error_point = example.path[-1]
    error_snapshot = completed_snapshots.get(format_point(error_point), {})
    return {
        "label": label,
        "source": example.source,
        "error": example.error,
        "error_code": f"{example.error_code:02X}",
        "predicate": example.predicate,
        "ordered_path": [format_point(point) for point in example.path],
        "verified": not missing and error_snapshot.get("A") == f"{example.error_code:02X}",
        "missing_path": missing,
        "completed_paths": completed_paths,
        "path_hits": {
            format_point(point): hits[point] for point in example.path
        },
        "causal_path_snapshots": completed_snapshots,
        "trace": {
            "sha256": digest(path),
            "bytes": path.stat().st_size,
            "instructions": instruction_count,
        },
    }


def build_report(
    rom_path: Path,
    traces: Sequence[tuple[str, Path]],
) -> dict[str, object]:
    if digest(rom_path) != TI84_PLUS_OS_255MP_SHA256:
        raise ValueError("ROM SHA-256 does not match TI-84 Plus OS 2.55MP")
    supplied = {label: path for label, path in traces}
    unknown = sorted(set(supplied) - set(EXAMPLES))
    missing = sorted(set(EXAMPLES) - set(supplied))
    if unknown or missing:
        details = []
        if unknown:
            details.append(f"unknown labels: {', '.join(unknown)}")
        if missing:
            details.append(f"missing labels: {', '.join(missing)}")
        raise ValueError("; ".join(details))
    rows = [analyze_trace(label, supplied[label]) for label in sorted(EXAMPLES)]
    rom = RomImage.from_path(rom_path)
    inventory = caller_inventory(rom)
    direct_callers = {row["ordered_path"][-2] for row in rows}
    return {
        "schema": 2,
        "rom": {"path": "tools/rom.bin", "sha256": digest(rom_path)},
        "scope": {
            "claim": "whole-ROM direct-reference inventory plus ordered natural-program witnesses for selected numeric error guards",
            "complete": False,
            "reason": "direct references are enumerated, but indirect transfers, shared helper predicates, and natural witnesses for every candidate remain open",
        },
        "caller_inventory": inventory,
        "examples": rows,
        "summary": {
            "examples": len(rows),
            "distinct_errors": len({row["error"] for row in rows}),
            "distinct_guard_paths": len({tuple(row["ordered_path"]) for row in rows}),
            "direct_reference_candidates": inventory["candidate_count"],
            "distinct_direct_callers_witnessed": len(direct_callers),
            "verified": sum(bool(row["verified"]) for row in rows),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--trace", action="append", type=parse_trace, default=[])
    args = parser.parse_args()
    labels = [label for label, _path in args.trace]
    if len(labels) != len(set(labels)):
        parser.error("trace labels must be unique")
    try:
        report = build_report(args.rom, args.trace)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    summary = report["summary"]
    print(
        f"wrote {args.output}: {summary['verified']} / "
        f"{summary['examples']} guard paths verified"
    )


if __name__ == "__main__":
    main()
