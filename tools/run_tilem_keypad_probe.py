#!/usr/bin/env python3
"""Run hash-guarded direct keypad and ON-edge cases through pinned TilEm."""

from __future__ import annotations

from probe_cli import Report, TilemProbeCli
from tilem_keypad import run_keypad_probe, validate_keypad_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable keypad summary."""

    native = report["native"]
    return (
        "matrix reads: "
        + ",".join(f"{value:02X}" for value in native["matrix"]),
        "ON observations: "
        + ",".join(f"{value:02X}" for value in native["on"]),
    )


PROBE = TilemProbeCli(
    runner=run_keypad_probe,
    validator=validate_keypad_report,
    launch="direct initialized-core keypad API and TI-84 Plus ports",
    evidence_scope=(
        "pinned TilEm matrix and ON-event behavior; not TI-OS execution, "
        "electrical settling, switch bounce, or physical ASIC ON edges"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
