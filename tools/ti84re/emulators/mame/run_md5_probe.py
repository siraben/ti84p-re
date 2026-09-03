#!/usr/bin/env python3
"""Run a guarded MD5-port coverage probe through MAME 0.287."""


from ti84re.emulators.mame.md5 import parse_mame_md5_report, validate_mame_md5_report
from ti84re.emulators.probe_cli import MameProbeCli, Report
from ti84re.paths import PROBES


def load_report(output: str) -> Report:
    return validate_mame_md5_report(parse_mame_md5_report(output))


def summarize(result: Report) -> list[str]:
    native = result["report"]["native"]
    return [
        "MD5 ports: initial and post-write reads are all zero; "
        f"valid step={native['observed_result']:08X} "
        f"(expected {native['expected_result']:08X})"
    ]


PROBE = MameProbeCli(
    lua_script=PROBES / "mame/mame_md5_probe.lua",
    seconds=2,
    load_report=load_report,
    launch=(
        "Lua reads and writes ports 0x18-0x1F through the main CPU I/O "
        "space, then issues the first padded-abc MD5 transaction"
    ),
    evidence_scope=(
        "MAME 0.287 TI-84 Plus I/O mapping and unmapped-port behavior; "
        "not TI-OS execution, MD5 hardware, or physical timing"
    ),
    summarize=summarize,
)


def main() -> None:
    PROBE.run(__doc__)


if __name__ == "__main__":
    main()
