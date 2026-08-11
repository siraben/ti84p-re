#!/usr/bin/env python3
"""Report the byte-verified archive-GC journal and optional trace transitions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from flash_trace import decode_amd_flash_commands
from gc_journal import (
    analyze_gc_journal,
    GcJournalSignatureError,
    journal_trace_events,
)
from hardware_trace import iter_resolved_memory_writes
from rom_image import RomImage


TOOLS = Path(__file__).resolve().parent


def build_report(analysis, trace_events=()) -> dict[str, Any]:
    """Convert the static analysis and optional dynamic events to JSON data."""

    return {
        "rom_sha256": analysis.rom_sha256,
        "block": {
            "offset": analysis.block_offset,
            "length": analysis.block_length,
            "end": analysis.block_offset + analysis.block_length,
        },
        "fields": [
            {
                "name": field.name,
                "relative_offset": field.relative_offset,
                "certificate_offset": field.certificate_offset,
                "helper": str(field.helper),
                "ram_addresses": list(field.ram_addresses),
                "role": field.role,
            }
            for field in analysis.fields
        ],
        "dispatch_entry": str(analysis.dispatch_entry),
        "phase_cases": [
            {
                "value": case.value,
                "branch": str(case.branch),
                "role": case.role,
                "continuation": (
                    str(case.continuation) if case.continuation else None
                ),
            }
            for case in analysis.phase_cases
        ],
        "phase_write_helper": str(analysis.phase_write_helper),
        "phase_writes": [
            {
                "value": write.value,
                "load": str(write.load),
                "call": str(write.call),
                "condition": write.condition,
            }
            for write in analysis.phase_writes
        ],
        "transitions": [
            {
                "source": transition.source,
                "destination": transition.destination,
                "condition": transition.condition,
            }
            for transition in analysis.transitions
        ],
        "sector_state_writer": str(analysis.sector_state_writer),
        "sector_state_writes": [
            {
                "value": write.value,
                "load": str(write.load),
                "call": str(write.call),
                "role": write.role,
            }
            for write in analysis.sector_state_writes
        ],
        "trace_events": [
            {
                "kind": event.kind,
                "clock": event.clock,
                "instruction_index": event.instruction_index,
                "physical_address": event.physical_address,
                "half_base": event.half_base,
                "certificate_offset": event.certificate_offset,
                "sector_index": event.sector_index,
                "value": event.value,
                "pc_space": event.pc_space,
                "pc_address": event.pc_address,
            }
            for event in trace_events
        ],
        "evidence_scope": (
            "static fields and transitions are ROM-byte verified; trace events are "
            "decoded state-changing CPU command-shaped writes, excluding 0xFF copy "
            "commands, and do not prove physical power-loss safety"
        ),
    }


def print_text(report: dict[str, Any]) -> None:
    block = report["block"]
    print(
        f"GC journal block: 0x{block['offset']:04X}-0x{block['end'] - 1:04X} "
        f"length=0x{block['length']:X}"
    )
    print("fields:")
    for field in report["fields"]:
        addresses = ", ".join(
            f"0x{address:04X}" for address in field["ram_addresses"]
        )
        print(
            f"  +0x{field['relative_offset']:02X} {field['name']}: "
            f"certificate=0x{field['certificate_offset']:04X} "
            f"helper={field['helper']} RAM={addresses}; {field['role']}"
        )
    print(f"phase dispatch: {report['dispatch_entry']}")
    for case in report["phase_cases"]:
        continuation = case["continuation"] or "return"
        print(
            f"  0x{case['value']:02X}: branch={case['branch']} "
            f"continuation={continuation}; {case['role']}"
        )
    print(f"phase writer: {report['phase_write_helper']}")
    for write in report["phase_writes"]:
        print(
            f"  0x{write['value']:02X}: {write['load']} -> {write['call']}; "
            f"{write['condition']}"
        )
    print("reachable master-phase transitions:")
    for transition in report["transitions"]:
        print(
            f"  0x{transition['source']:02X} -> "
            f"0x{transition['destination']:02X}: {transition['condition']}"
        )
    if report["trace_events"]:
        print("trace journal writes:")
        for event in report["trace_events"]:
            slot = (
                ""
                if event["sector_index"] is None
                else f" sector-index={event['sector_index']}"
            )
            pc = (
                "unknown"
                if event["pc_space"] is None
                else f"{event['pc_space']}:{event['pc_address']:04X}"
            )
            print(
                f"  clk={event['clock']} {event['kind']}{slot} "
                f"offset=0x{event['certificate_offset']:04X} "
                f"value=0x{event['value']:02X} pc={pc}"
            )


def _trace_events(path: Path, *, initial_mapping: str, resync: bool):
    writes = (
        event
        for event in iter_resolved_memory_writes(
            path,
            initial_mapping=initial_mapping,
            resync=resync,
        )
        if not event.unresolved and event.target_kind == "flash"
    )
    return journal_trace_events(decode_amd_flash_commands(writes))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=TOOLS / "rom.bin")
    parser.add_argument("--trace", type=Path)
    parser.add_argument(
        "--initial-mapping",
        choices=("unknown", "ti84p-reset"),
        default="ti84p-reset",
        help="mapping at the first trace record (default: ti84p-reset)",
    )
    parser.add_argument(
        "--resync",
        action="store_true",
        help="resynchronize after malformed trace records",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        analysis = analyze_gc_journal(RomImage.from_path(args.rom))
        trace_events = (
            _trace_events(
                args.trace,
                initial_mapping=args.initial_mapping,
                resync=args.resync,
            )
            if args.trace
            else ()
        )
    except (OSError, GcJournalSignatureError, ValueError) as error:
        parser.error(str(error))
    report = build_report(analysis, trace_events)
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print_text(report)


if __name__ == "__main__":
    main()
