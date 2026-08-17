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
    return {
        "schema": 1,
        "rom": {"path": "tools/rom.bin", "sha256": digest(rom_path)},
        "scope": {
            "claim": "ordered natural-program witnesses for five numeric error guards",
            "complete": False,
            "reason": "the report distinguishes selected causes; it does not enumerate every caller of each shared error shim",
        },
        "examples": rows,
        "summary": {
            "examples": len(rows),
            "distinct_errors": len({row["error"] for row in rows}),
            "distinct_guard_paths": len({tuple(row["ordered_path"]) for row in rows}),
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
