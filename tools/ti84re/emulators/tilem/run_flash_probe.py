#!/usr/bin/env python3
"""Run a hash-guarded Flash command/status matrix through pinned TilEm."""

from __future__ import annotations

from ti84re.emulators.probe_cli import Report, TilemProbeCli
from ti84re.emulators.tilem.flash import run_flash_probe, validate_flash_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable Flash summary."""

    native = report["native"]
    return (
        "program deadlines/status: "
        f"{native['legal_timer']} clocks {native['legal_reads']}; "
        f"illegal {native['illegal_busy_reads']} -> {native['illegal_error_reads']}",
        "sector erase: "
        f"{native['sector_erased']} bytes, deadlines "
        f"{native['sector_wait_timer']}/{native['sector_erase_timer']} clocks",
        "chip erase non-FF bytes: "
        f"default {native['chip_default_non_ff']}, "
        f"override {native['chip_override_non_ff']}",
    )


PROBE = TilemProbeCli(
    runner=run_flash_probe,
    validator=validate_flash_report,
    launch=(
        "direct initialized-core Flash command writes and reads with "
        "synthetic in-memory contents"
    ),
    evidence_scope=(
        "pinned TilEm command, status, protection-group, and timer model; "
        "not retail-ROM or physical Flash behavior"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
