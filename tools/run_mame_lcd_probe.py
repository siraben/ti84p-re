#!/usr/bin/env python3
"""Run guarded T6A04 LCD-controller cases through MAME 0.287."""

from pathlib import Path

from mame_lcd import parse_mame_lcd_report, validate_mame_lcd_report
from probe_cli import MameProbeCli, Report

TOOLS = Path(__file__).resolve().parent


def load_report(output: str) -> Report:
    return validate_mame_lcd_report(parse_mame_lcd_report(output))


def summarize(result: Report) -> list[str]:
    native = result["report"]["native"]
    return [
        "controller: "
        f"reset={native['reset_status10']:02X}, "
        f"rapid={native['rapid_status']}, "
        f"increment={native['increment_cells']}",
        "hidden columns: "
        f"15={native['direct_column15_cell']:02X}, "
        f"31={native['direct_column31_cell']:02X}; "
        f"latch={native['latch_reads']}",
        f"ASIC ready={native['ready']:02X}; ports 29-2F remain zero",
    ]


PROBE = MameProbeCli(
    lua_script=TOOLS / "mame_lcd_probe.lua",
    seconds=2,
    load_report=load_report,
    launch=(
        "Lua parks the CPU in isolated RAM, drives mirrored LCD ports "
        "through CPU I/O space, reads the startup-reset state, and "
        "seeds named save items between independent cases"
    ),
    evidence_scope=(
        "MAME 0.287 generic T6A04 state, safe backing-array indices, "
        "and TI-84 Plus port mapping; not physical controller behavior"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
