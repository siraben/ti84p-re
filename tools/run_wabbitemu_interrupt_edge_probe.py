#!/usr/bin/env python3
"""Run guarded interrupt-controller edges through pinned Wabbitemu."""

from __future__ import annotations

from probe_cli import Report, WabbitemuProbeCli
from wabbitemu_headless import run_interrupt_edge_probe
from wabbitemu_interrupt_probe import validate_interrupt_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable interrupt summary."""

    native = report["native"]
    return (
        f"mask: {native['initial_mask']:02X}→{native['stored_mask']:02X}; "
        f"ON ack={int(native['on_latch_before_ack'])}→"
        f"{int(native['on_latch_after_ack'])}",
        f"timer boundary: {native['exact_boundary_status']:02X}→"
        f"{native['after_boundary_status']:02X}; "
        f"port-3/port-2 ack={native['after_port3_ack_status']:02X}/"
        f"{native['after_port2_ack_status']:02X}",
    )


PROBE = WabbitemuProbeCli(
    runner=run_interrupt_edge_probe,
    validator=validate_interrupt_report,
    launch="direct initialized-core interrupt and low-power port calls",
    evidence_scope=(
        "pinned Wabbitemu mask, ON latch, standard-timer rate and boundary, "
        "acknowledgement, programmable-completion, and LCD low-power behavior; "
        "not TI-OS execution, wall-clock timing, physical interrupt edges, or "
        "ASIC power-domain evidence"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
