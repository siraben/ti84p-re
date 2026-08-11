#!/usr/bin/env python3
"""Report byte-verified certificate rebuild modes and validity metadata."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Any

from certificate_rebuild import (
    analyze_certificate_rebuild,
    CertificateRebuildSignatureError,
)
from rom_image import RomImage


TOOLS = Path(__file__).resolve().parent


def _span_report(span) -> dict[str, int | str]:
    return {
        "offset": span.offset,
        "length": span.length,
        "end": span.end,
        "range": f"0x{span.offset:04X}-0x{span.end - 1:04X}",
    }


def build_report(analysis) -> dict[str, Any]:
    """Convert a library analysis to a JSON-safe report."""

    app_validity = asdict(analysis.app_validity)
    for key in ("locator", "set_routine", "clear_routine"):
        app_validity[key] = str(getattr(analysis.app_validity, key))
    app_restrictions = asdict(analysis.app_restrictions)
    for key in ("set_entry", "remove_entry", "query_entry"):
        app_restrictions[key] = str(getattr(analysis.app_restrictions, key))
    app_restrictions["control_span"] = _span_report(
        analysis.app_restrictions.control_span
    )
    os_validity = asdict(analysis.os_validity)
    for key in ("mark_invalid_entry", "mark_valid_entry", "check_entry"):
        os_validity[key] = str(getattr(analysis.os_validity, key))
    os_validity["invalid_rebuild_span"] = _span_report(
        analysis.os_validity.invalid_rebuild_span
    )
    app_trials = asdict(analysis.app_trials)
    for key in (
        "clear_routine",
        "write_routine",
        "query_routine",
        "display_entry",
        "display_label_location",
    ):
        app_trials[key] = str(getattr(analysis.app_trials, key))
    app_trials["delete_callers"] = [
        str(location) for location in analysis.app_trials.delete_callers
    ]
    tail_accessors = []
    for accessor in analysis.tail_accessors:
        tail_accessors.append(
            {
                "entry": str(accessor.entry),
                "role": accessor.role,
                "fixed_offset": accessor.fixed_offset,
                "direct_callers": [
                    str(location) for location in accessor.direct_callers
                ],
            }
        )
    model_selected_offset = asdict(analysis.model_selected_offset)
    for key in ("accessor", "probe"):
        model_selected_offset[key] = str(
            getattr(analysis.model_selected_offset, key)
        )
    return {
        "rom_sha256": analysis.rom_sha256,
        "dispatcher": str(analysis.dispatcher),
        "tail_blocks": [_span_report(span) for span in analysis.tail_blocks],
        "modes": [
            {
                "mode": mode.mode,
                "branch": str(mode.branch),
                "helper_calls": [str(location) for location in mode.helper_calls],
                "rewritten_spans": [
                    _span_report(span) for span in mode.rewritten_spans
                ],
            }
            for mode in analysis.modes
        ],
        "direct_calls": [
            {
                "mode": call.mode,
                "load": str(call.load),
                "call": str(call.call),
            }
            for call in analysis.direct_calls
        ],
        "bjump_calls": [
            {
                "mode": call.mode,
                "load": str(call.load),
                "call": str(call.call),
                "stub": str(call.stub),
            }
            for call in analysis.bjump_calls
        ],
        "mode_owners": [
            {
                "mode": owner.mode,
                "role": owner.role,
                "owner_entry": str(owner.owner_entry),
                "dispatcher_call": str(owner.dispatcher_call),
                "call_chain": [str(location) for location in owner.call_chain],
            }
            for owner in analysis.mode_owners
        ],
        "os_validity": os_validity,
        "app_trials": app_trials,
        "app_validity": app_validity,
        "app_restrictions": app_restrictions,
        "tail_accessors": tail_accessors,
        "model_selected_offset": model_selected_offset,
        "evidence_scope": (
            "ROM byte signatures and control/data flow, plus resolved TI-84 Plus "
            "port-trace values; external certificate field names are not used"
        ),
    }


def print_text(report: dict[str, Any]) -> None:
    print(f"dispatcher: {report['dispatcher']}")
    print("certificate tail blocks:")
    for span in report["tail_blocks"]:
        print(f"  {span['range']} length=0x{span['length']:X}")
    print("modes:")
    direct_by_mode = {
        call["mode"]: call["call"] for call in report["direct_calls"]
    }
    bjump_by_mode = {
        call["mode"]: f"{call['call']} via {call['stub']}"
        for call in report["bjump_calls"]
    }
    for mode in report["modes"]:
        spans = ", ".join(span["range"] for span in mode["rewritten_spans"])
        invocation = direct_by_mode.get(
            mode["mode"], bjump_by_mode.get(mode["mode"], "none")
        )
        helpers = ", ".join(mode["helper_calls"])
        print(
            f"  {mode['mode']}: branch={mode['branch']} invocation={invocation} "
            f"rewrites={spans} helpers={helpers}"
        )
    print("resolved mode owners:")
    for owner in report["mode_owners"]:
        chain = " -> ".join(owner["call_chain"])
        print(f"  {owner['mode']}: {owner['role']}; chain={chain}")
    os_validity = report["os_validity"]
    valid_state = "clear" if os_validity["valid_when_clear"] else "set"
    print("OS-validity flag:")
    print(
        f"  offset=0x{os_validity['offset']:04X} "
        f"mask=0x{os_validity['mask']:02X}; OS is valid when the bit is {valid_state}"
    )
    print(
        f"  mark invalid=0x{os_validity['mark_invalid_bcall_id']:04X} "
        f"({os_validity['mark_invalid_entry']}), "
        f"mark valid=0x{os_validity['mark_valid_bcall_id']:04X} "
        f"({os_validity['mark_valid_entry']}), "
        f"check=0x{os_validity['check_bcall_id']:04X} "
        f"({os_validity['check_entry']})"
    )
    trials = report["app_trials"]
    offsets = ", ".join(f"0x{offset:04X}" for offset in trials["model_offsets"])
    print("App trial table:")
    print(
        f"  model offsets={offsets}; length=0x{trials['length']:X}; "
        f"entry length={trials['entry_length']}"
    )
    print(
        f"  clear={trials['clear_routine']} via mode "
        f"{trials['clear_rebuild_mode']}; write={trials['write_routine']}; "
        f"query={trials['query_routine']}"
    )
    print("certificate-tail accessors:")
    for accessor in report["tail_accessors"]:
        if accessor["fixed_offset"] is None:
            offset = "model-selected"
        else:
            offset = f"0x{accessor['fixed_offset']:04X}"
        callers = ", ".join(accessor["direct_callers"])
        print(
            f"  {accessor['entry']}: {accessor['role']}; offset={offset}; "
            f"callers={callers}"
        )
    selection = report["model_selected_offset"]
    values = ", ".join(
        f"0x{value:02X}" for value in selection["ti84_plus_observed_port_values"]
    )
    print("model-selected certificate offset:")
    print(
        f"  {selection['accessor']} calls {selection['probe']}; port "
        f"0x{selection['port']:02X} mask 0x{selection['mask']:02X}; "
        f"set -> 0x{selection['set_bit_offset']:04X}, "
        f"clear -> 0x{selection['clear_bit_offset']:04X}"
    )
    print(
        f"  TI-84 Plus observed values={values}; selected offset="
        f"0x{selection['ti84_plus_selected_offset']:04X}"
    )
    validity = report["app_validity"]
    print("App-validity bitmap update:")
    print(
        f"  bitmap starts at 0x{validity['bitmap_offset']:04X}; "
        f"{validity['bit_order']}"
    )
    print(
        f"  set={validity['set_routine']} via mode "
        f"{validity['set_rebuild_mode']}; clear={validity['clear_routine']} "
        f"via bcall 0x{validity['clear_bcall_id']:04X}"
    )
    restrictions = report["app_restrictions"]
    print("App restrictions:")
    print(
        f"  set=0x{restrictions['set_bcall_id']:04X} "
        f"({restrictions['set_entry']}), "
        f"remove=0x{restrictions['remove_bcall_id']:04X} "
        f"({restrictions['remove_entry']}), "
        f"query=0x{restrictions['query_bcall_id']:04X} "
        f"({restrictions['query_entry']})"
    )
    print(
        f"  control={restrictions['control_span']['range']} "
        f"remove rebuild mode={restrictions['remove_rebuild_mode']}"
    )
    print(
        f"  control byte=0x{restrictions['control_offset']:04X}; "
        f"App bitmap=0x{restrictions['app_bitmap_offset']:04X}-"
        f"0x{restrictions['app_bitmap_offset'] + restrictions['app_bitmap_length'] - 1:04X}; "
        f"{restrictions['bitmap_bit_order']}"
    )
    for type_behavior in restrictions["types"]:
        print(
            f"  type {type_behavior['value']}: {type_behavior['role']}; "
            f"set={type_behavior['set_behavior']}; "
            f"query={type_behavior['query_behavior']}; "
            f"remove={type_behavior['remove_behavior']}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rom", type=Path, default=TOOLS / "rom.bin")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = build_report(analyze_certificate_rebuild(RomImage.from_path(args.rom)))
    except (OSError, CertificateRebuildSignatureError) as error:
        parser.error(str(error))
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print_text(report)


if __name__ == "__main__":
    main()
