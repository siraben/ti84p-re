#!/usr/bin/env python3
"""Run hash-guarded raw-link and link-assist cases through pinned TilEm."""

from __future__ import annotations

from ti84re.emulators.probe_cli import Report, TilemProbeCli
from ti84re.emulators.tilem.link import run_link_probe, validate_link_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable link summary."""

    native = report["native"]
    raw_rows = " / ".join(
        ",".join(f"{value:02X}" for value in native["raw_reads"][start : start + 4])
        for start in range(0, 16, 4)
    )
    return (
        f"raw rows: {raw_rows}",
        f"assist: send={native['send'][0]:02X}, "
        f"receive={native['receive'][0]:02X}, error={native['error'][0]:02X}",
    )


PROBE = TilemProbeCli(
    runner=run_link_probe,
    validator=validate_link_report,
    launch="direct initialized-core raw-link and assist port handlers",
    evidence_scope=(
        "pinned TilEm raw and link-assist state transitions; not TI-OS "
        "execution, virtual-cable lifecycle, electrical levels, physical "
        "edge timing, or connected-calculator behavior"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
