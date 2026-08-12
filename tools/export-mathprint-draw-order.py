#!/usr/bin/env python3
"""Export compact, ordered LCD mutations from retained MathPrint traces."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tilem_trace_resolve import KEY_NAMES, iter_records, read_header
from trace_lcd import VISIBLE_WIDTH, ROWS, replay_mutations


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT = ROOT / "tools" / "mathprint-trace-report.json"
DEFAULT_OUTPUT = ROOT / "web" / "mathprint" / "draw-order.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def last_key_press(path: Path) -> tuple[int, int]:
    instruction_index = 0
    last = None
    with path.open("rb") as stream:
        read_header(stream)
        for record_type, payload in iter_records(stream):
            if record_type == 0x01:
                instruction_index += 1
            elif record_type == 0x03 and payload[0]:
                last = (instruction_index, payload[1])
    if last is None:
        raise ValueError(f"trace has no injected key press: {path}")
    return last


def encode_grid(grid: list[list[int]]) -> list[str]:
    return ["".join("1" if pixel else "0" for pixel in row) for row in grid]


def scenario_record(name: str, expression: str, trace: Path, expected_hash: str):
    actual_hash = sha256_file(trace)
    if actual_hash != expected_hash:
        raise ValueError(
            f"{name}: trace hash mismatch; expected {expected_hash}, got {actual_hash}"
        )
    start_index, key = last_key_press(trace)
    replay = replay_mutations(trace, from_index=start_index)
    return {
        "expression": expression,
        "trace_sha256": actual_hash,
        "start": {
            "instruction_index": start_index,
            "reason": "state immediately before the final injected key press is processed",
            "key": KEY_NAMES.get(key, f"0x{key:02X}"),
        },
        "width": VISIBLE_WIDTH,
        "height": ROWS,
        "initial": encode_grid(replay.initial),
        "events": [
            {
                "instruction_index": event.instruction_index,
                "clock": event.clock,
                "port": event.port,
                "value": event.value,
                "pointer": [event.pointer_x, event.pointer_y],
                "mode": event.mode,
                "changes": [list(change) for change in event.changes],
            }
            for event in replay.events
        ],
        "final": encode_grid(replay.final),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "scenario",
        nargs="+",
        metavar="NAME=TRACE",
        help="report scenario key and its retained TLMT trace path",
    )
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    scenarios = {}
    for value in args.scenario:
        name, separator, trace_name = value.partition("=")
        if not separator or name not in report["scenarios"]:
            parser.error(f"invalid scenario mapping: {value}")
        source = report["scenarios"][name]
        scenarios[source["expression"]] = scenario_record(
            name,
            source["expression"],
            Path(trace_name),
            source["trace_sha256"],
        )
    output = {
        "schema": 1,
        "source": "accepted visible-pixel mutations from TilEm TLMT v2 LCD writes",
        "scenarios": scenarios,
    }
    args.out.write_text(json.dumps(output, separators=(",", ":")) + "\n")
    print(
        f"wrote {args.out}: "
        + ", ".join(
            f"{expression}={len(record['events'])} writes"
            for expression, record in scenarios.items()
        )
    )


if __name__ == "__main__":
    main()
