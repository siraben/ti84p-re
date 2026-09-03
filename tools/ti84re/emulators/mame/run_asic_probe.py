#!/usr/bin/env python3
"""Run guarded TI-84 Plus ASIC-control cases through MAME 0.287."""


from ti84re.emulators.mame.asic import parse_mame_asic_report, validate_mame_asic_report
from ti84re.emulators.probe_cli import MameProbeCli, Report
from ti84re.paths import PROBES


def load_report(output: str) -> Report:
    return validate_mame_asic_report(parse_mame_asic_report(output))


def summarize(result: Report) -> list[str]:
    native = result["report"]["native"]
    return [
        "gate status: "
        + "/".join(f"{value:02X}" for value in native["gate_status"])
        + "; port 14 remains write-only",
        f"clock loop: {native['clock_low_count']}→{native['clock_high_count']} "
        f"in {native['clock_low_attoseconds'] / 1e18:.1f} s; "
        f"soft reset retains 14/20/21={native['soft_status02']:02X}/"
        f"{native['soft_speed20']:02X}/{native['soft_control21']:02X}",
    ]


PROBE = MameProbeCli(
    lua_script=PROBES / "mame/mame_asic_probe.lua",
    seconds=4,
    load_report=load_report,
    launch=(
        "Lua drives mapped and absent I/O through the CPU space, runs a "
        "50-T-state RAM counter at both clocks, and schedules a soft reset"
    ),
    evidence_scope=(
        "MAME 0.287 TI-84 Plus status, raw Flash-gate byte, speed clock, "
        "port-0x21 mask, absent protection/GPIO ports, disconnected USB "
        "constants, and soft-reset retention; not physical ASIC behavior"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
