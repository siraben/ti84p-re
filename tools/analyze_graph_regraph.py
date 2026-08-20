#!/usr/bin/env python3
"""Reduce natural function-mode graph traces to stable pipeline evidence."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from hardware_trace import make_banker
from rom_signatures import TI84_PLUS_OS_255MP_SHA256
from tilem_trace_resolve import (
    IDX_AF,
    IDX_BC,
    IDX_CLOCK,
    IDX_DE,
    IDX_HL,
    iter_records,
    read_header,
    resolve_instruction,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = ROOT / "tools" / "rom.bin"
TILEM_SOURCE = "https://github.com/siraben/tilem-headless"
TILEM_COMMIT = "d1bdc58dd321ae462a701e556fcb62bb925a78b1"
TILEM_BINARY_SHA256 = "cdd257c57b918b8f0b05df6e49f249d4f0461a7c1ed2d9b87fe76fc3d2b0e1ee"

PLOT_SCREEN = range(0x9340, 0x9640)
CUR_G_STYLE = 0x8D17
CUR_INC = 0x8E67
XRES_INT = 0x9151
ITERATOR_WORD_9810 = 0x9810
ITERATOR_WORD_980E = 0x980E

POINTS = {
    "regraph_entry": ("page_04", 0x6764),
    "regraph_return": ("page_04", 0x6985),
    "buffer_clear": ("page_04", 0x6071),
    "function_mode_setup": ("page_04", 0x68D6),
    "sample_eval_prepare": ("page_04", 0x710F),
    "sample_cleanup": ("page_04", 0x7045),
    "sample_advance": ("page_04", 0x69CF),
    "next_equation": ("page_04", 0x70AD),
    "parser_entry": ("page_38", 0x5975),
    "equation_eval_entry": ("page_38", 0x778F),
    "equation_eval_finish": ("page_38", 0x77C2),
    "documented_parseinp": ("page_38", 0x5987),
    "token_prescan": ("page_33", 0x5023),
    "selected_table_next": ("page_33", 0x707A),
    "x_to_pixel": ("page_37", 0x41EB),
    "y_to_pixel": ("page_37", 0x41DF),
    "pixel_round": ("page_37", 0x4229),
    "coordinate_return": ("page_37", 0x420E),
    "integer_line": ("page_04", 0x4029),
    "integer_point": ("page_04", 0x4157),
    "error_divide_by_zero": ("ram", 0x26EC),
    "error_domain": ("ram", 0x26F4),
}

SCENARIOS = {
    "x_squared": {
        "formula": "Y1=X^2",
        "macro": "tools/macros/graph-y1-x2.macro",
        "expected_style": 0,
    },
    "reciprocal": {
        "formula": "Y1=X^-1",
        "macro": "tools/macros/graph-y1-reciprocal.macro",
        "expected_style": 0,
    },
}


def format_location(space: str, address: int) -> str:
    """Render one resolved address in the repository's house notation."""

    prefix = space.removeprefix("page_")
    return f"{prefix}:{address:04X}"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def summarize_sequence(values: list[int]) -> dict[str, object]:
    """Describe an ordered byte sequence without retaining every occurrence."""

    if not values:
        return {"count": 0, "first": None, "last": None, "distinct": 0, "stride": None}
    strides = {right - left for left, right in zip(values, values[1:])}
    return {
        "count": len(values),
        "first": values[0],
        "last": values[-1],
        "distinct": len(set(values)),
        "stride": strides.pop() if len(strides) == 1 else None,
    }


def _word(memory: bytearray, address: int) -> int:
    return memory[address] | memory[address + 1] << 8


def analyze_trace(path: Path) -> dict[str, object]:
    """Extract one complete `_Regraph` interval from a TLMT v2 trace."""

    point_names = {location: name for name, location in POINTS.items()}
    banker = make_banker("ti84p-reset")
    pending_writes: list[tuple[int, int]] = []
    point_counts: Counter[str] = Counter()
    post_mode_counts: Counter[str] = Counter()
    buffer_writers: Counter[tuple[str, int]] = Counter()
    sample_columns: list[int] = []
    transform_columns: list[int] = []
    line_entries: list[dict[str, int]] = []
    error_columns: list[int] = []
    coordinate_witnesses: dict[str, dict[str, dict[str, object]]] = {}
    coordinate_axis: str | None = None
    style_values: set[int] = set()
    active = False
    function_mode = False
    entry_index = return_index = None
    entry_clock = return_clock = None
    return_memory: bytes | None = None
    total_instructions = 0
    buffer_writes = 0
    buffer_mutations = 0
    regraph_count = 0

    with path.open("rb") as stream:
        header = read_header(stream)
        if header["version"] != 2:
            raise ValueError(f"{path}: expected TLMT v2, got v{header['version']}")
        if len(header["init"]) != 0x10000:
            raise ValueError(f"{path}: expected a 64 KiB initial logical-memory snapshot")
        memory = bytearray(header["init"])

        for record_type, payload in iter_records(stream):
            if record_type == 0x02:
                pending_writes.append(payload)
                continue
            if record_type != 0x01:
                continue

            total_instructions += 1
            resolved, _switch = resolve_instruction(banker, payload)
            location = (resolved[0], resolved[1])

            if location == POINTS["regraph_entry"]:
                if active:
                    raise ValueError(f"{path}: nested `_Regraph` interval")
                active = True
                function_mode = False
                regraph_count += 1
                entry_index = total_instructions
                entry_clock = payload[IDX_CLOCK]

            if active:
                name = point_names.get(location)
                if name is not None:
                    point_counts[name] += 1
                    if function_mode:
                        post_mode_counts[name] += 1
                if location == POINTS["function_mode_setup"]:
                    function_mode = True
                    post_mode_counts["function_mode_setup"] += 1
                if location == POINTS["sample_advance"]:
                    sample_columns.append(memory[CUR_INC])
                    style_values.add(memory[CUR_G_STYLE])
                if function_mode and location in {
                    POINTS["x_to_pixel"], POINTS["y_to_pixel"]
                }:
                    transform_columns.append(memory[CUR_INC])
                    coordinate_axis = "x" if location == POINTS["x_to_pixel"] else "y"
                    coordinate_witnesses.setdefault(coordinate_axis, {})
                if function_mode and coordinate_axis is not None and location in {
                    POINTS["x_to_pixel"],
                    POINTS["y_to_pixel"],
                    POINTS["pixel_round"],
                    POINTS["coordinate_return"],
                }:
                    phase = {
                        POINTS["x_to_pixel"]: "entry",
                        POINTS["y_to_pixel"]: "entry",
                        POINTS["pixel_round"]: "round",
                        POINTS["coordinate_return"]: "return",
                    }[location]
                    snapshot = {
                        "instruction_index": total_instructions,
                        "clock": payload[IDX_CLOCK],
                        "column": memory[CUR_INC],
                        "registers": {
                            "af": payload[IDX_AF],
                            "bc": payload[IDX_BC],
                            "de": payload[IDX_DE],
                            "hl": payload[IDX_HL],
                        },
                        "tifloats": {
                            "op1": bytes(memory[0x8478:0x8481]).hex(),
                            "x_work": bytes(memory[0x8E6A:0x8E73]).hex(),
                            "x_origin": bytes(memory[0x8E73:0x8E7C]).hex(),
                            "y_min": bytes(memory[0x8F6B:0x8F74]).hex(),
                            "short_x": bytes(memory[0x9164:0x916D]).hex(),
                            "short_y": bytes(memory[0x916D:0x9176]).hex(),
                        },
                    }
                    if phase == "entry":
                        input_address = payload[IDX_DE]
                        snapshot["input_at_de"] = {
                            "address": format_location("ram", input_address),
                            "bytes": bytes(memory[input_address : input_address + 9]).hex(),
                        }
                    coordinate_witnesses[coordinate_axis].setdefault(phase, snapshot)
                    if phase == "return":
                        coordinate_axis = None
                if function_mode and location == POINTS["integer_line"]:
                    line_entries.append({
                        "mode": payload[IDX_AF] >> 8,
                        "x1": payload[IDX_BC] >> 8,
                        "y1": payload[IDX_BC] & 0xFF,
                        "x2": payload[IDX_DE] >> 8,
                        "y2": payload[IDX_DE] & 0xFF,
                    })
                if function_mode and location in {
                    POINTS["error_divide_by_zero"], POINTS["error_domain"]
                }:
                    error_columns.append(memory[CUR_INC])

                for address, value in pending_writes:
                    if address in PLOT_SCREEN:
                        buffer_writes += 1
                        buffer_writers[location] += 1
                        if memory[address] != value:
                            buffer_mutations += 1

            for address, value in pending_writes:
                if 0 <= address < len(memory):
                    memory[address] = value
            pending_writes.clear()

            if active and location == POINTS["regraph_return"]:
                return_index = total_instructions
                return_clock = payload[IDX_CLOCK]
                return_memory = bytes(memory)
                active = False
                function_mode = False

    if active:
        raise ValueError(f"{path}: `_Regraph` entry has no matching return")
    if (
        regraph_count != 1
        or entry_index is None
        or return_index is None
        or return_memory is None
    ):
        raise ValueError(f"{path}: expected exactly one complete `_Regraph`, found {regraph_count}")

    plot = return_memory[PLOT_SCREEN.start : PLOT_SCREEN.stop]
    distinct_transform_columns = sorted(set(transform_columns))
    center_column = 47
    center_neighborhood = [
        row for row in line_entries
        if max(row["x1"], row["x2"]) >= center_column - 2
        and min(row["x1"], row["x2"]) <= center_column + 2
    ]
    return {
        "sha256": digest(path),
        "bytes": path.stat().st_size,
        "total_trace_instructions": total_instructions,
        "regraph_interval": {
            "entry_instruction": entry_index,
            "return_instruction": return_index,
            "instructions": return_index - entry_index,
            "clocks": (return_clock - entry_clock) & 0xFFFFFFFF,
        },
        "point_visits": dict(sorted(point_counts.items())),
        "not_observed": sorted(set(POINTS) - set(point_counts)),
        "post_function_mode_visits": dict(sorted(post_mode_counts.items())),
        "sample_columns_before_advance": summarize_sequence(sample_columns),
        "xres_int_at_return": return_memory[XRES_INT],
        "styles_seen_at_sample_advance": sorted(style_values),
        "iterator_words_at_return": {
            "ram:9810": _word(return_memory, ITERATOR_WORD_9810),
            "ram:980E": _word(return_memory, ITERATOR_WORD_980E),
        },
        "coordinate_transform_columns": {
            "visits": len(transform_columns),
            "distinct": len(distinct_transform_columns),
            "first": distinct_transform_columns[0] if distinct_transform_columns else None,
            "last": distinct_transform_columns[-1] if distinct_transform_columns else None,
        },
        "coordinate_witnesses": coordinate_witnesses,
        "integer_line_entries": {
            "count": len(line_entries),
            "zero_length": sum(
                row["x1"] == row["x2"] and row["y1"] == row["y2"]
                for row in line_entries
            ),
            "first": line_entries[0] if line_entries else None,
            "last": line_entries[-1] if line_entries else None,
            "center_column": center_column,
            "bridges_center": sum(
                min(row["x1"], row["x2"]) < center_column
                < max(row["x1"], row["x2"])
                for row in line_entries
            ),
            "center_neighborhood": center_neighborhood,
        },
        "error_state_columns": error_columns,
        "plot_screen": {
            "bytes": len(plot),
            "writes": buffer_writes,
            "mutations": buffer_mutations,
            "nonzero_bytes": sum(value != 0 for value in plot),
            "set_pixels": sum(value.bit_count() for value in plot),
            "sha256": hashlib.sha256(plot).hexdigest(),
            "writers": [
                {"location": format_location(space, address), "writes": count}
                for (space, address), count in sorted(
                    buffer_writers.items(), key=lambda item: (-item[1], item[0])
                )
            ],
        },
    }


def build_report(
    traces: dict[str, Path],
    *,
    rom: Path = DEFAULT_ROM,
    emulator: Path,
) -> dict[str, object]:
    unknown = set(traces) - set(SCENARIOS)
    if unknown:
        raise ValueError(f"unknown scenario label(s): {', '.join(sorted(unknown))}")
    rom_digest = digest(rom)
    if rom_digest != TI84_PLUS_OS_255MP_SHA256:
        raise ValueError("ROM SHA-256 does not match the pinned TI-84 Plus OS 2.55MP image")
    emulator_digest = digest(emulator)
    if emulator_digest != TILEM_BINARY_SHA256:
        raise ValueError("TilEm binary SHA-256 does not match the traced headless build")
    return {
        "schema": 1,
        "rom": {"path": "tools/rom.bin", "sha256": rom_digest},
        "emulator": {
            "source": TILEM_SOURCE,
            "commit": TILEM_COMMIT,
            "binary_sha256": emulator_digest,
        },
        "scope": (
            "natural function-mode GRAPH runs; raw TLMT traces remain outside the repository"
        ),
        "entry_points": {
            name: format_location(space, address)
            for name, (space, address) in POINTS.items()
        },
        "scenarios": {
            label: {**SCENARIOS[label], **analyze_trace(path)}
            for label, path in sorted(traces.items())
        },
        "interpretation_limits": [
            "point counts establish the executed path, not all possible graph modes",
            "the retained line-style traces do not exercise thick, shade, animate, or dotted styles",
            "token_prescan and documented_parseinp are retained as negative observations, not dead-code claims",
        ],
        "executed_entry_relationship": (
            "The grapher reaches 38:5975 (`parse_init_findsym`), which performs "
            "parser initialization and joins the shared evaluator tail at 38:59A4. "
            "Official `_ParseInp` at 38:5987 is a sibling entry with additional state "
            "clearing and stack cleanup; neither natural graph trace executes 38:5987."
        ),
    }


def parse_trace(value: str) -> tuple[str, Path]:
    label, separator, path = value.partition("=")
    if not separator or not label or not path:
        raise argparse.ArgumentTypeError("trace must be LABEL=PATH")
    return label, Path(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", action="append", type=parse_trace, required=True)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
    parser.add_argument("--emulator", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    traces = dict(args.trace)
    if len(traces) != len(args.trace):
        parser.error("trace labels must be unique")
    try:
        report = build_report(traces, rom=args.rom, emulator=args.emulator)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for label, row in report["scenarios"].items():
        interval = row["regraph_interval"]
        print(
            f"{label}: {interval['instructions']:,} `_Regraph` instructions, "
            f"{row['sample_columns_before_advance']['count']} samples, "
            f"{row['plot_screen']['set_pixels']} final pixels"
        )


if __name__ == "__main__":
    main()
