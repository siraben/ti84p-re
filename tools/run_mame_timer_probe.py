#!/usr/bin/env python3
"""Run guarded programmable-timer and absent-RTC cases through MAME 0.287."""

from pathlib import Path

from mame_timer import parse_mame_timer_report, validate_mame_timer_report
from probe_cli import MameProbeCli, Report

TOOLS = Path(__file__).resolve().parent


def load_report(output: str) -> Report:
    return validate_mame_timer_report(parse_mame_timer_report(output))


def summarize(result: Report) -> list[str]:
    native = result["report"]["native"]
    return [
        "fixed-crystal counts: "
        + ", ".join(f"{value:02X}" for value in native["family_counts"])
        + f" after {native['family_elapsed_attoseconds']} attoseconds",
        "expiry: "
        f"zero={native['zero_count']:02X}, "
        f"bit1-set-port4={native['bit1_set_port4']:02X}, "
        f"bit1-clear-port4={native['bit1_clear_port4']:02X}, "
        f"loop-final={native['loop_count']:02X}",
        f"global completion clear: {native['global_before']:02X}→"
        f"{native['global_after']:02X}",
    ]


PROBE = MameProbeCli(
    lua_script=TOOLS / "mame_timer_probe.lua",
    seconds=2,
    load_report=load_report,
    launch=(
        "Lua parks the CPU in isolated RAM, drives timer registers "
        "through CPU I/O space, and advances with machine frames"
    ),
    evidence_scope=(
        "MAME 0.287 TI-84 Plus programmable-timer callbacks, status, "
        "and absent RTC mapping; not TI-OS timing or physical hardware"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
