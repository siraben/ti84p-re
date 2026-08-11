#!/usr/bin/env python3
"""Run guarded CPU-speed and delay-register edges through pinned Wabbitemu."""

from __future__ import annotations

from probe_cli import Report, WabbitemuProbeCli
from wabbitemu_headless import run_speed_edge_probe
from wabbitemu_speed_probe import validate_speed_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable speed summary."""

    native = report["native"]
    return (
        "default modes: "
        + "/".join(str(value) for value in native["default_speed_reads"])
        + "; front-end modes: "
        + "/".join(str(value) for value in native["extra_speed_reads"]),
        "wait masks: "
        + "/".join(f"{value:02X}" for value in native["wait_masks"])
        + f"; port 2D readback={native['port2d_read']:02X}",
    )


PROBE = WabbitemuProbeCli(
    runner=run_speed_edge_probe,
    validator=validate_speed_report,
    launch="direct initialized-core speed and delay-register port calls",
    evidence_scope=(
        "pinned Wabbitemu speed masks, internal extra-speed configuration, "
        "raw delay latches, wait-gate selection, and port-0x2D handler side "
        "effects; not retail-ROM execution, host timing, electrical timing, "
        "or physical low-power behavior"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
