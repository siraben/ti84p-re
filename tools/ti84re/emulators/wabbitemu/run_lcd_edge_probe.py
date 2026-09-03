#!/usr/bin/env python3
"""Run guarded LCD and bus-timing edges through pinned Wabbitemu."""

from __future__ import annotations

from ti84re.emulators.probe_cli import Report, WabbitemuProbeCli
from ti84re.emulators.wabbitemu.headless import run_lcd_edge_probe
from ti84re.emulators.wabbitemu.lcd_probe import validate_lcd_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable LCD summary."""

    native = report["native"]
    latch = ",".join(f"{value:02X}" for value in native["latch_reads"])
    return (
        f"LCD guard: early={native['early_status']:02X}, "
        f"boundary={native['boundary_status']:02X}; latch={latch}",
        f"columns: 14={native['wrap_column14']:02X}, "
        f"15={native['wrap_column15']:02X}, 0={native['wrap_column0']:02X}; "
        f"ready={native['ready_hold']}T, "
        f"delay={native['delay_after'] - native['delay_before']}T",
    )


PROBE = WabbitemuProbeCli(
    runner=run_lcd_edge_probe,
    validator=validate_lcd_report,
    launch="direct initialized-core LCD and bus-timing port calls",
    evidence_scope=(
        "pinned Wabbitemu transfer guard, pointer, latch, mapped-port, "
        "ready-interval, delay, memory-wait, and speed-clamp behavior; "
        "not retail-ROM execution, host timing, electrical bus timing, "
        "or physical LCD/ASIC behavior"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
