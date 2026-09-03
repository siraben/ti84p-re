#!/usr/bin/env python3
"""Run guarded reset-retention cases through pinned Wabbitemu."""

from __future__ import annotations

from ti84re.emulators.probe_cli import Report, WabbitemuProbeCli
from ti84re.emulators.wabbitemu.headless import run_reset_retention_probe
from ti84re.emulators.wabbitemu.reset import RETAINED_COMPONENTS, validate_reset_report


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable reset summary."""

    native = report["native"]
    retained_count = sum(native["retained"])
    return (
        f"CPU_reset retained {retained_count}/{len(RETAINED_COMPONENTS)} seeded "
        "component groups; mapping="
        + "/".join(f"{page:02X}" for page in native["reset_pages"]),
        f"frontend LCD active={int(native['frontend_lcd_active'])}, "
        f"last_tstate={native['frontend_lcd_last_tstate']}; violation PCs="
        f"{native['program_violation_pc']:04X}/{native['error_violation_pc']:04X}",
    )


PROBE = WabbitemuProbeCli(
    runner=run_reset_retention_probe,
    validator=validate_reset_report,
    launch=(
        "direct initialized-core CPU_reset, frontend-equivalent LCD reset, "
        "and execution-violation CPU_step calls"
    ),
    evidence_scope=(
        "pinned Wabbitemu reset implementation and directly seeded retention; "
        "not retail-ROM reset code, power-on ASIC defaults, or physical "
        "calculator retention"
    ),
    summarize=summarize,
    exact_binary=True,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
