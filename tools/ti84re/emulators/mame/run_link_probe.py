#!/usr/bin/env python3
"""Run a guarded raw-link and advertised-assist probe through MAME 0.287."""


from ti84re.emulators.mame.link import parse_mame_link_report, validate_mame_link_report
from ti84re.emulators.probe_cli import MameProbeCli, Report
from ti84re.paths import PROBES


def load_report(output: str) -> Report:
    return validate_mame_link_report(parse_mame_link_report(output))


def summarize(result: Report) -> list[str]:
    native = result["report"]["native"]
    return [
        "raw link: reads "
        + ", ".join(f"{case['read']:02X}" for case in native["raw_cases"][:4])
        + "; normal writes release both connector lines",
        f"assist: status={native['status']:02X}, ports 08-0D remain zero",
    ]


PROBE = MameProbeCli(
    lua_script=PROBES / "mame/mame_link_probe.lua",
    seconds=2,
    load_report=load_report,
    launch=(
        "Lua exercises raw and assist ports through the main CPU I/O "
        "space and reads the link-port device's connector save items"
    ),
    evidence_scope=(
        "MAME 0.287 TI-84 Plus PCR, connector callbacks, peer input "
        "fields, and I/O mapping; not TI-OS transfer or physical wiring"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
