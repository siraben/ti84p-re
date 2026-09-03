#!/usr/bin/env python3
"""Run a guarded Flash command-family matrix through pinned Wabbitemu."""

from __future__ import annotations

from ti84re.emulators.probe_cli import Report, WabbitemuProbeCli
from ti84re.emulators.wabbitemu.flash_probe import validate_command_report
from ti84re.emulators.wabbitemu.headless import run_flash_command_probe


def summarize(report: Report) -> tuple[str, ...]:
    """Format the stable human-readable Flash-command summary."""

    native = report["native"]
    return (
        "autoselect: "
        f"{native['autoselect_maker']:02X}/{native['autoselect_device']:02X}, "
        f"protection {native['autoselect_protection']:02X}",
        "fast program: "
        f"{native['fast_first_stored']:02X}, {native['fast_second_stored']:02X}; "
        f"exit state {native['fast_exit_step']}",
        f"sector erase: {native['sector_erased_bytes']} bytes; "
        f"outside changes {native['sector_outside_changed_bytes']}",
        f"chip erase: {native['chip_non_ff_before']} non-FF bytes to "
        f"{native['chip_non_ff_after']}",
    )


PROBE = WabbitemuProbeCli(
    runner=run_flash_command_probe,
    validator=validate_command_report,
    launch=(
        "direct initialized-core setup; command writes and reads use "
        "CPU_mem_write and CPU_mem_read; erase mutations remain in memory"
    ),
    evidence_scope=(
        "pinned Wabbitemu core command-state behavior checked against "
        "its source model; not retail-ROM or physical Flash behavior"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
