#!/usr/bin/env python3
"""Run guarded TI-84 Plus legacy-interrupt cases through MAME 0.287."""


from ti84re.emulators.mame.interrupt import parse_mame_interrupt_report, validate_mame_interrupt_report
from ti84re.emulators.probe_cli import MameProbeCli, Report
from ti84re.paths import PROBES


def load_report(output: str) -> Report:
    return validate_mame_interrupt_report(parse_mame_interrupt_report(output))


def summarize(result: Report) -> list[str]:
    native = result["report"]["native"]
    return [
        "status reads: "
        f"03={native['reset_status03']:02X}, 04={native['reset_status04']:02X}; "
        f"injected 07={native['injected_seed07']:02X}",
        "ON edge: "
        f"masked={native['on_masked_press']:02X}, "
        f"enabled={native['on_enabled_press']:02X}, "
        f"released={native['on_enabled_release']:02X}",
        "soft reset: "
        f"immediate={native['soft_immediate04']:02X}, "
        f"timers={native['soft_after_timers']:02X}, "
        f"ON={native['soft_after_on']:02X}",
    ]


PROBE = MameProbeCli(
    lua_script=PROBES / "mame/mame_interrupt_probe.lua",
    seconds=5,
    load_report=load_report,
    launch=(
        "Lua parks the Z80 in DI RAM, drives :ON, accesses legacy "
        "interrupt ports through CPU I/O space, and schedules a soft reset"
    ),
    evidence_scope=(
        "MAME 0.287 TI-84 Plus legacy status, mask, ON edge, fixed "
        "standard timers, and reset retention; not physical ASIC behavior"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
