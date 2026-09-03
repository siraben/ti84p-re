#!/usr/bin/env python3
"""Report the byte-verified archive-GC journal and optional trace transitions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from ti84re.flash.trace import decode_amd_flash_commands
from ti84re.flash.gc_journal import (
    analyze_gc_journal,
    GcJournalSignatureError,
    journal_trace_events,
)
from ti84re.trace.hardware import iter_resolved_memory_writes
from ti84re.rom.image import RomImage
from ti84re.paths import DEFAULT_ROM


def build_report(analysis, trace_events=()) -> dict[str, Any]:
    """Convert the static analysis and optional dynamic events to JSON data."""

    initialization = analysis.initialization
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
        "initialization": {
            "load_current_entry": str(initialization.load_current_entry),
            "initialize_entry": str(initialization.initialize_entry),
            "port": initialization.port,
            "mask": initialization.mask,
            "set_bit_ram_base": initialization.set_bit_ram_base,
            "set_bit_erased_length": initialization.set_bit_erased_length,
            "set_bit_sector_state_capacity": (
                initialization.set_bit_erased_length - 6
            ),
            "clear_bit_ram_base": initialization.clear_bit_ram_base,
            "clear_bit_erased_length": initialization.clear_bit_erased_length,
            "clear_bit_sector_state_capacity": (
                initialization.clear_bit_erased_length - 6
            ),
            "erased_byte": initialization.erased_byte,
            "certificate_rebuild_entry": str(
                initialization.certificate_rebuild_entry
            ),
            "certificate_rebuild_length": (
                initialization.certificate_rebuild_length
            ),
            "retained_tail_offset": initialization.retained_tail_offset,
            "retained_tail_length": initialization.retained_tail_length,
            "ti84_plus_archive_limit": initialization.ti84_plus_archive_limit,
            "ti84_plus_live_sector_state_count": (
                initialization.ti84_plus_live_sector_state_count
            ),
            "maximum_archive_limit": initialization.maximum_archive_limit,
            "maximum_live_sector_state_count": (
                initialization.maximum_live_sector_state_count
            ),
        },
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
    initialization = report["initialization"]
    retained_tail_end = (
        initialization["retained_tail_offset"]
        + initialization["retained_tail_length"]
        - 1
    )
    print("initialization:")
    print(
        f"  port 0x{initialization['port']:02X} mask "
        f"0x{initialization['mask']:02X}; set-bit RAM="
        f"0x{initialization['set_bit_ram_base']:04X} fills "
        f"0x{initialization['set_bit_erased_length']:X} bytes with 0xFF "
        f"({initialization['set_bit_sector_state_capacity']} state slots)"
    )
    print(
        f"  clear-bit RAM=0x{initialization['clear_bit_ram_base']:04X} fills "
        f"0x{initialization['clear_bit_erased_length']:X} bytes with 0xFF "
        f"({initialization['clear_bit_sector_state_capacity']} state slots)"
    )
    print(
        f"  rebuild={initialization['certificate_rebuild_entry']} length="
        f"0x{initialization['certificate_rebuild_length']:X}; retained tail="
        f"+0x{initialization['retained_tail_offset']:02X}-"
        f"+0x{retained_tail_end:02X}"
    )
    print(
        f"  TI-84 Plus archive limit=0x{initialization['ti84_plus_archive_limit']:02X} "
        f"uses at most {initialization['ti84_plus_live_sector_state_count']} slots; "
        f"largest ROM limit=0x{initialization['maximum_archive_limit']:02X} uses "
        f"at most {initialization['maximum_live_sector_state_count']} slots"
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
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM)
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
