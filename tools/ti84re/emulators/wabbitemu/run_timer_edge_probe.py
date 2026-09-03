#!/usr/bin/env python3
"""Run guarded programmable-timer and RTC edges through pinned Wabbitemu."""

from __future__ import annotations

from ti84re.emulators.probe_cli import Report, WabbitemuProbeCli
from ti84re.emulators.wabbitemu.headless import run_timer_edge_probe
from ti84re.emulators.wabbitemu.timer_probe import validate_timer_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable timer summary."""

    native = report["native"]
    reads = ",".join(f"{value:02X}" for value in native["crystal_reads"])
    return (
        f"crystal reads: {reads}; CPU catch-up: {native['cpu_count_read']:02X}; "
        f"zero status: {native['zero_status']:02X}",
        "HALT interrupt: "
        f"{int(native['interrupt_while_halted'])}→"
        f"{int(native['interrupt_after_resume'])}; "
        f"frozen RTC: {native['rtc_frozen']:08X}",
    )


PROBE = WabbitemuProbeCli(
    runner=run_timer_edge_probe,
    validator=validate_timer_report,
    launch=(
        "direct initialized-core timer/RTC ports with explicit emulated "
        "clock advancement"
    ),
    evidence_scope=(
        "pinned Wabbitemu programmable-timer and RTC behavior checked "
        "against its source model; not retail-ROM execution, wall-clock "
        "timing, low-power electrical behavior, or physical ASIC behavior"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
