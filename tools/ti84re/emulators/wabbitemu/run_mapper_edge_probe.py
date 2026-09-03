#!/usr/bin/env python3
"""Run guarded mapper edges through pinned Wabbitemu."""

from __future__ import annotations

from ti84re.emulators.probe_cli import Report, WabbitemuProbeCli
from ti84re.emulators.wabbitemu.headless import run_mapper_edge_probe
from ti84re.emulators.wabbitemu.mapper_probe import validate_mapper_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable mapper summary."""

    native = report["native"]
    return (
        f"handoff: data={native['fixed_page_after_data_read']:02X}, "
        f"opcode={native['fixed_page_after_opcode']:02X}",
        f"paired: A/B/C={native['paired_a_page']:02X}/"
        f"{native['paired_b_page']:02X}/{native['paired_c_page']:02X}; "
        f"overlay fetch halt={int(native['independent_fetch_halted'])}→"
        f"{int(native['paired_fetch_halted'])}",
    )


PROBE = WabbitemuProbeCli(
    runner=run_mapper_edge_probe,
    validator=validate_mapper_report,
    launch="direct initialized-core mapper port and memory calls",
    evidence_scope=(
        "pinned Wabbitemu reset mapping, fixed-page opcode handoff, selector "
        "readback, paired-page expression, and independent-versus-paired "
        "overlay routing for reads, low-level writes, and fetched bytes; not "
        "TI-OS execution, physical mapper behavior, or Flash command acceptance"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
