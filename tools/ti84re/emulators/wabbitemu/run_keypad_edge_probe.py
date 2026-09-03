#!/usr/bin/env python3
"""Run guarded keypad and ON-key edges through pinned Wabbitemu."""

from __future__ import annotations

from ti84re.emulators.probe_cli import Report, WabbitemuProbeCli
from ti84re.emulators.wabbitemu.headless import run_keypad_edge_probe
from ti84re.emulators.wabbitemu.keypad_probe import validate_keypad_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable keypad summary."""

    native = report["native"]
    return (
        "matrix reads: "
        f"single={native['single_read']:02X}, "
        f"same-column={native['same_column_read']:02X}, "
        f"rectangle={native['rectangle_read']:02X}, "
        f"transitive={native['transitive_read']:02X}, "
        f"unwired={native['unwired_read']:02X}",
        "ON status: "
        f"press={native['on_press_before_eval']:02X}→"
        f"{native['on_press_after_eval']:02X}, "
        f"held-after-ack={native['on_held_after_eval']:02X}, "
        f"second-press={native['on_second_press_after_eval']:02X}",
    )


PROBE = WabbitemuProbeCli(
    runner=run_keypad_edge_probe,
    validator=validate_keypad_report,
    launch=(
        "direct initialized-core keypad ports and standard-interrupt "
        "device evaluation"
    ),
    evidence_scope=(
        "pinned Wabbitemu keypad and ON behavior checked against its "
        "source model; not retail-ROM execution, electrical settling, "
        "or physical ASIC behavior"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
