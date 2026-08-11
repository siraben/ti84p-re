#!/usr/bin/env python3
"""Run guarded Fake USB handler edges through pinned Wabbitemu."""

from __future__ import annotations

from probe_cli import Report, WabbitemuProbeCli
from wabbitemu_headless import run_usb_edge_probe
from wabbitemu_usb_probe import validate_usb_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable Fake USB summary."""

    native = report["native"]
    return (
        f"ports: 0x54 active={int(native['port54_active'])}, "
        f"accepted={int(native['port54_read_accepted'])}, "
        f"fallback={native['port54_read']:02X}",
        f"event: line={native['event_line_state']:02X}, "
        f"events={native['event_events']:02X}, "
        f"summary={native['event_port55']:02X}, "
        f"repeat_irq={int(native['repeated_event_interrupt'])}",
    )


PROBE = WabbitemuProbeCli(
    runner=run_usb_edge_probe,
    validator=validate_usb_report,
    launch="direct initialized-core Fake USB port calls",
    evidence_scope=(
        "pinned Wabbitemu port registration, reset reads, mask-independent and "
        "repeatable line events, active-low summary, latches, and directly "
        "seeded handler contracts; not TI-OS execution, connected endpoint "
        "transactions, electrical behavior, or physical-calculator evidence"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
