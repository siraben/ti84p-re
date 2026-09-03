#!/usr/bin/env python3
"""Run hash-guarded battery-comparator cases through pinned TilEm."""

from __future__ import annotations

from ti84re.emulators.probe_cli import Report, TilemProbeCli
from ti84re.emulators.tilem.battery import run_battery_probe, validate_battery_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable battery summary."""

    model = report["source_model"]
    return (
        "reachable levels: " + ",".join(map(str, model["reachable_rom_levels"])),
        "unreachable levels: "
        + ",".join(map(str, model["unreachable_rom_levels"])),
    )


PROBE = TilemProbeCli(
    runner=run_battery_probe,
    validator=validate_battery_report,
    launch="direct initialized-core battery comparator sweep",
    evidence_scope=(
        "pinned TilEm port-0x02 comparator behavior; not TI-OS "
        "execution, measured voltages, or physical ASIC thresholds"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
