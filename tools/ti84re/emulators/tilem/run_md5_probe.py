#!/usr/bin/env python3
"""Run hash-guarded MD5-assist edge cases through pinned TilEm."""

from __future__ import annotations

from ti84re.emulators.probe_cli import Report, TilemProbeCli
from ti84re.emulators.tilem.md5 import run_md5_probe, validate_md5_report


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


PROBE = TilemProbeCli(
    runner=run_md5_probe,
    validator=validate_md5_report,
    launch="direct initialized-core MD5-assist port handlers",
    evidence_scope=(
        "pinned TilEm MD5 edge behavior under the locked compiler; not "
        "TI-OS execution, a portable C result, or physical ASIC behavior"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
