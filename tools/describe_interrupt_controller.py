#!/usr/bin/env python3
"""Decode interrupt registers or summarize interrupt I/O from a TilEm trace."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from hardware_trace import iter_resolved_io_events
from interrupt_controller import (
    acknowledge_legacy_sources,
    decode_port03,
    decode_port04_configuration,
    decode_port04_status,
    rom_status_test_order,
    standard_timer_period,
    usb_active_low_sources,
)
from tilem_trace_resolve import parse_clock_range


def integer(value: str) -> int:
    return int(value, 0)


def mask_report(value: int) -> dict[str, object]:
    mask = decode_port03(value)
    return {
        **asdict(mask),
        "low_power_on_halt": mask.low_power_on_halt,
        "enabled_sources": list(mask.enabled_sources),
        "tilem_programmable_timers_can_wake_halt": (
            mask.tilem_programmable_timers_can_wake_halt
        ),
    }


def status_report(value: int) -> dict[str, object]:
    status = decode_port04_status(value)
    return {
        **asdict(status),
        "legacy_pending_sources": list(status.legacy_pending_sources),
        "finished_programmable_timers": list(
            status.finished_programmable_timers
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit JSON")
    commands = parser.add_subparsers(dest="command", required=True)

    mask = commands.add_parser("mask", help="decode a port-0x03 value")
    mask.add_argument("value", type=integer)

    status = commands.add_parser("status", help="decode a port-0x04 read")
    status.add_argument("value", type=integer)

    config = commands.add_parser("config", help="decode a port-0x04 write")
    config.add_argument("value", type=integer)

    ack = commands.add_parser("ack", help="apply a port-0x03 acknowledgement")
    ack.add_argument("pending", type=integer)
    ack.add_argument("write", type=integer)

    trace = commands.add_parser("trace", help="summarize interrupt-port trace events")
    trace.add_argument("path", type=Path)
    trace.add_argument(
        "--clock",
        type=parse_clock_range,
        metavar="START[-END]",
        help="include events in this trace-clock range",
    )
    trace.add_argument(
        "--initial-mapping",
        choices=("unknown", "ti84p-reset"),
        default="ti84p-reset",
    )
    trace.add_argument("--limit", type=int, default=0)
    trace.add_argument(
        "--all",
        action="store_true",
        help="show consecutive duplicate polling events",
    )
    trace.add_argument("--resync", action="store_true")
    return parser


def static_report(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "mask":
        return {"port03": mask_report(args.value)}
    if args.command == "status":
        report = status_report(args.value)
        report["status_test_order"] = list(rom_status_test_order(args.value))
        return {"port04_status": report}
    if args.command == "config":
        report = asdict(decode_port04_configuration(args.value))
        timer1 = standard_timer_period(args.value, 1)
        timer2 = standard_timer_period(args.value, 2)
        report["timer1_period_seconds"] = float(timer1)
        report["timer2_period_seconds"] = float(timer2)
        report["timer1_period_fraction"] = str(timer1)
        report["timer2_period_fraction"] = str(timer2)
        return {"port04_configuration": report}
    return {
        "pending_before": args.pending,
        "port03_write": args.write,
        "pending_after": acknowledge_legacy_sources(args.pending, args.write),
    }


def event_annotation(port: int, direction: str, value: int | None) -> dict[str, object]:
    if value is None:
        return {}
    if port == 0x03:
        return {"mask": mask_report(value)}
    if port == 0x04 and direction == "in":
        return {
            "status": status_report(value),
            "status_test_order": list(rom_status_test_order(value)),
        }
    if port == 0x04:
        return {"configuration": asdict(decode_port04_configuration(value))}
    if port == 0x55:
        return {"active_low_sources": usb_active_low_sources(value)}
    if port == 0x56:
        return {"usb_line_events": value}
    return {}


def trace_report(args: argparse.Namespace) -> dict[str, object]:
    events = []
    previous = None
    omitted = 0
    for event in iter_resolved_io_events(
        args.path,
        ports={0x03, 0x04, 0x55, 0x56},
        initial_mapping=args.initial_mapping,
        resync=args.resync,
    ):
        if args.clock is not None and not args.clock[0] <= event.clock <= args.clock[1]:
            continue
        direction = event.direction.lower()
        key = (
            event.space,
            event.address,
            direction,
            event.port,
            event.value,
        )
        if not args.all and key == previous:
            omitted += 1
            continue
        previous = key
        item = {
            "instruction_index": event.instruction_index,
            "clock": event.clock,
            "location": f"{event.space}:{event.address:04X}",
            "direction": direction,
            "port": event.port,
            "value": event.value,
            **event_annotation(event.port, direction, event.value),
        }
        events.append(item)
        if args.limit and len(events) >= args.limit:
            break
    return {"trace": str(args.path), "omitted_duplicate_polls": omitted, "events": events}


def print_text(report: dict[str, object]) -> None:
    if "port03" in report:
        mask = report["port03"]
        enabled = ",".join(mask["enabled_sources"]) or "none"
        print(
            f"port03=0x{mask['raw']:02X} enabled={enabled} "
            f"halt={'powered' if mask['keep_power_during_halt'] else 'low-power'}"
        )
        return
    if "port04_status" in report:
        status = report["port04_status"]
        pending = ",".join(status["legacy_pending_sources"]) or "none"
        finished = ",".join(status["finished_programmable_timers"]) or "none"
        order = ",".join(status["status_test_order"]) or "none"
        print(
            f"port04=0x{status['raw']:02X} legacy-pending={pending} "
            f"programmable-finished={finished} "
            f"ON={'released' if status['on_released'] else 'pressed'} "
            f"status-tests={order}"
        )
        return
    if "port04_configuration" in report:
        config = report["port04_configuration"]
        print(
            f"port04=0x{config['raw']:02X} "
            f"mapping={'paired' if config['paired_mapping'] else 'independent'} "
            f"timer-index={config['standard_timer_index']} "
            f"timer1={config['timer1_period_seconds']:.9f}s "
            f"timer2={config['timer2_period_seconds']:.9f}s "
            f"battery-selector={config['battery_selector']}"
        )
        return
    if "pending_after" in report:
        print(
            f"pending 0x{report['pending_before']:02X} --port03 "
            f"0x{report['port03_write']:02X}--> 0x{report['pending_after']:02X}"
        )
        return

    for event in report["events"]:
        arrow = "->" if event["direction"] == "in" else "<-"
        value = "?" if event["value"] is None else f"0x{event['value']:02X}"
        details = ""
        if "mask" in event:
            sources = ",".join(event["mask"]["enabled_sources"]) or "none"
            details = f" enabled={sources}"
        elif "status" in event:
            pending = ",".join(
                event["status"]["legacy_pending_sources"]
            ) or "none"
            finished = ",".join(
                event["status"]["finished_programmable_timers"]
            ) or "none"
            details = f" legacy-pending={pending} programmable-finished={finished}"
        elif "active_low_sources" in event:
            details = f" active-low=0x{event['active_low_sources']:02X}"
        print(
            f"{event['instruction_index']:9d} clk={event['clock']:<10d} "
            f"{event['location']} {event['direction'].upper()} "
            f"(0x{event['port']:02X}) {arrow} {value}{details}"
        )
    if report["omitted_duplicate_polls"]:
        print(f"# omitted {report['omitted_duplicate_polls']} duplicate poll(s)")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        report = trace_report(args) if args.command == "trace" else static_report(args)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print_text(report)


if __name__ == "__main__":
    main()
