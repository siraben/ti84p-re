#!/usr/bin/env python3
"""Run hash-guarded direct interrupt cases through pinned TilEm."""

from __future__ import annotations

from ti84re.emulators.probe_cli import Report, TilemProbeCli
from ti84re.emulators.tilem.interrupt import run_interrupt_probe, validate_interrupt_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable interrupt summary."""

    native = report["native"]
    return (
        "reset port03/internal ON/power: "
        f"{native['reset'][0]:02X}/{native['reset'][2]}/{native['reset'][3]}",
        "ON status: " + ",".join(f"{value:02X}" for value in native["on_status"]),
        "timer status: "
        + ",".join(f"{value:02X}" for value in native["timer_status"]),
    )


PROBE = TilemProbeCli(
    runner=run_interrupt_probe,
    validator=validate_interrupt_report,
    launch="direct initialized-core port, input, timer, link, and reset calls",
    evidence_scope=(
        "pinned TilEm interrupt-controller behavior; not TI-OS execution, "
        "physical ASIC behavior, electrical signaling, or measured timing"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
