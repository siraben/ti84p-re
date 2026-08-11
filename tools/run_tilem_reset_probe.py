#!/usr/bin/env python3
"""Run hash-guarded direct reset and violation cases through pinned TilEm."""

from __future__ import annotations

from probe_cli import Report, TilemProbeCli
from tilem_reset import (
    RESET_GROUPS,
    RETAINED_COMPONENTS,
    run_reset_probe,
    validate_reset_report,
)


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable reset summary."""

    native = report["native"]
    return (
        f"reset groups {sum(native['reset_groups'])}/{len(RESET_GROUPS)}; "
        f"retained groups {sum(native['retained'])}/{len(RETAINED_COMPONENTS)}",
        f"violation stop={native['violation_stop']:02X}, "
        f"RAM marker={native['violation_ram_marker']:02X}, "
        f"post-reset PC={native['violation_pc']:04X}",
    )


PROBE = TilemProbeCli(
    runner=run_reset_probe,
    validator=validate_reset_report,
    launch=(
        "direct initialized-core tilem_calc_reset and synthetic forbidden "
        "Flash opcode execution"
    ),
    evidence_scope=(
        "pinned TilEm reset functions and exception ordering; not TI-OS "
        "reset code, physical ASIC reset, or power-loss retention"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
