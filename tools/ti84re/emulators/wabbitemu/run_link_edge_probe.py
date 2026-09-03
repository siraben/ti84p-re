#!/usr/bin/env python3
"""Run guarded raw-link and assist edges through pinned Wabbitemu."""

from __future__ import annotations

from ti84re.emulators.probe_cli import Report, WabbitemuProbeCli
from ti84re.emulators.wabbitemu.headless import run_link_edge_probe
from ti84re.emulators.wabbitemu.link_probe import validate_link_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable link summary."""

    native = report["native"]
    raw_rows = " / ".join(
        ",".join(f"{value:02X}" for value in native["raw_reads"][start : start + 4])
        for start in range(0, 16, 4)
    )
    return (
        f"raw rows: {raw_rows}",
        f"assist: send={native['assist_send_out']:02X}/"
        f"{native['assist_send_status']:02X}, "
        f"receive={native['assist_receive_in']:02X}/"
        f"{native['assist_receive_status']:02X}, "
        f"error={native['assist_error_status']:02X}→"
        f"{native['assist_error_after_read_status']:02X}",
    )


PROBE = WabbitemuProbeCli(
    runner=run_link_edge_probe,
    validator=validate_link_report,
    launch="direct initialized-core raw-link and assist port calls",
    evidence_scope=(
        "pinned Wabbitemu raw truth table, mapped assist ports, status, "
        "interrupt, LSB-first send/receive, and read-to-clear behavior; "
        "not TI-OS execution, virtual-cable lifecycle, electrical levels, "
        "physical edge timing, or connected-calculator evidence"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
