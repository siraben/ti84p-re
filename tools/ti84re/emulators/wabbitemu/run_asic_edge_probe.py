#!/usr/bin/env python3
"""Run guarded ASIC status, identity, protection, and GPIO edges."""

from __future__ import annotations

from ti84re.emulators.probe_cli import Report, WabbitemuProbeCli
from ti84re.emulators.wabbitemu.asic_probe import validate_asic_report
from ti84re.emulators.wabbitemu.headless import run_asic_edge_probe


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable ASIC summary."""

    native = report["native"]
    return (
        f"status: locked={native['port02_locked']:02X}, "
        f"unlocked={native['port02_unlocked']:02X}; "
        f"identity={native['port15_ram_v0']:02X}/{native['port15_ram_v2']:02X}",
        f"port 0x21: locked accepted={int(native['locked_write_accepted'])}, "
        f"mode-3 internal/read={native['mode3_internal_mode']}/"
        f"{native['mode3_read']:02X}; GPIO latch={native['port3a_second_read']:02X}",
    )


PROBE = WabbitemuProbeCli(
    runner=run_asic_edge_probe,
    validator=validate_asic_report,
    launch="direct initialized-core ASIC-control port calls",
    evidence_scope=(
        "pinned Wabbitemu status, identity, protection, and GPIO behavior "
        "checked against its source model; not retail-ROM execution, "
        "battery voltage, GPIO electrical behavior, or physical ASIC proof"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
