#!/usr/bin/env python3
"""Run a guarded live-input keypad matrix through MAME 0.287."""

from pathlib import Path

from mame_keypad import parse_mame_keypad_report, validate_mame_keypad_report
from probe_cli import MameProbeCli, Report

TOOLS = Path(__file__).resolve().parent


def load_report(output: str) -> Report:
    return validate_mame_keypad_report(parse_mame_keypad_report(output))


def summarize(result: Report) -> list[str]:
    native = {case["name"]: case for case in result["report"]["native"]["cases"]}
    return [
        "matrix reads: "
        f"single={native['single']['read']:02X}, "
        f"unselected={native['unselected']['read']:02X}, "
        f"same-column={native['same_column']['read']:02X}, "
        f"rectangle={native['rectangle']['read']:02X}",
        "bounds: "
        f"bit-7-only={native['bit7_only']['read']:02X}, "
        f"column-7={native['column_seven']['read']:02X}, "
        f"all-selected={native['all_selected']['read']:02X}",
    ]


PROBE = MameProbeCli(
    lua_script=TOOLS / "mame_keypad_probe.lua",
    seconds=2,
    load_report=load_report,
    launch=(
        "Lua injects exact group/column fields through :BIT0-:BIT7 "
        "and reads port 0x01 through the main CPU I/O space"
    ),
    evidence_scope=(
        "MAME 0.287 TI-84 Plus live input fields and keypad handlers; "
        "not TI-OS scanning, electrical settling, or physical hardware"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
