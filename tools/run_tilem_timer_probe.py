#!/usr/bin/env python3
"""Run hash-guarded direct timer and RTC cases through pinned TilEm."""

from __future__ import annotations

from probe_cli import Report, TilemProbeCli
from tilem_timer import run_timer_probe, validate_timer_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable timer summary."""

    native = report["native"]
    return (
        "crystal periods: " + ",".join(map(str, native["crystal_us"])),
        "expiry statuses: "
        + ",".join(f"{native['expiry'][index]:X}" for index in range(0, 25, 5)),
        "RTC running/frozen/torn: "
        f"{native['rtc'][3]:08X}/{native['rtc'][4]:08X}/{native['rtc'][11]:08X}",
    )


PROBE = TilemProbeCli(
    runner=run_timer_probe,
    validator=validate_timer_report,
    launch=(
        "direct initialized-core timer ports and callbacks with a "
        "probe-controlled time_t source"
    ),
    evidence_scope=(
        "pinned TilEm timer and RTC behavior; not TI-OS execution, host "
        "wall-clock accuracy, or physical ASIC timing and retention"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
