#!/usr/bin/env python3
"""Run guarded MD5 edge cases through pinned Wabbitemu."""

from __future__ import annotations

from ti84re.emulators.probe_cli import Report, WabbitemuProbeCli
from ti84re.emulators.wabbitemu.headless import run_md5_edge_probe
from ti84re.emulators.wabbitemu.md5_probe import validate_md5_edge_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable MD5 summary."""

    native = report["native"]
    return (
        "operand shifts: "
        f"{native['one_write_result']:08X}, {native['three_write_result']:08X}, "
        f"{native['four_write_result']:08X}, {native['five_write_result']:08X}",
        f"masked controls: {native['masked_control_result']:08X}; "
        f"mixed read: {native['mixed_result']:08X}",
    )


PROBE = WabbitemuProbeCli(
    runner=run_md5_edge_probe,
    validator=validate_md5_edge_report,
    launch="direct initialized-core device_input/device_output calls",
    evidence_scope=(
        "pinned Wabbitemu MD5-port behavior checked against independent "
        "arithmetic; not retail-ROM execution or physical ASIC behavior"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
